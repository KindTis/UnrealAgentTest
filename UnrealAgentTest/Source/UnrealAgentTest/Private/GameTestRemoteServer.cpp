#include "GameTestRemoteServer.h"

#include "GameTestCommandService.h"
#include "GameTestQueryService.h"
#include "Async/Async.h"
#include "IPAddress.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/SceneCapture2D.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Camera/PlayerCameraManager.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HttpPath.h"
#include "HttpServerModule.h"
#include "HttpServerResponse.h"
#include "HAL/Runnable.h"
#include "HAL/RunnableThread.h"
#include "HAL/PlatformProcess.h"
#include "Logging/LogMacros.h"
#include "Misc/DateTime.h"
#include "Misc/Base64.h"
#include "Misc/DefaultValueHelper.h"
#include "Misc/ScopeLock.h"
#include "Misc/SecureHash.h"
#include "HAL/PlatformTime.h"
#include "Modules/ModuleManager.h"
#include "RHI.h"
#include "Slate/SceneViewport.h"
#include "Widgets/SWindow.h"
#include "IImageWrapperModule.h"
#include "SocketSubsystemModule.h"
#include "SocketSubsystem.h"
#include "Sockets.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#if WITH_EDITOR
#include "Editor.h"
#include "PlayInEditorDataTypes.h"
#endif

DEFINE_LOG_CATEGORY_STATIC(LogGameTestRemoteServer, Log, All);

namespace
{
	static const TCHAR* WebSocketMagicGuid = TEXT("258EAFA5-E914-47DA-95CA-C5AB0DC85B11");

	FString GetQueryOrDefault(const FHttpServerRequest& Request, const FString& Key, const FString& DefaultValue = TEXT(""))
	{
		if (const FString* Value = Request.QueryParams.Find(Key))
		{
			return Value->TrimStartAndEnd();
		}

		return DefaultValue;
	}

	bool TryGetQueryDouble(const FHttpServerRequest& Request, const FString& Key, double& OutValue)
	{
		if (const FString* Value = Request.QueryParams.Find(Key))
		{
			const FString Trimmed = Value->TrimStartAndEnd();
			return !Trimmed.IsEmpty() && FDefaultValueHelper::ParseDouble(Trimmed, OutValue);
		}

		return false;
	}

	bool TryGetQueryBool(const FHttpServerRequest& Request, const FString& Key, bool& OutValue)
	{
		if (const FString* Value = Request.QueryParams.Find(Key))
		{
			const FString Trimmed = Value->TrimStartAndEnd().ToLower();
			if (Trimmed == TEXT("1") || Trimmed == TEXT("true") || Trimmed == TEXT("yes"))
			{
				OutValue = true;
				return true;
			}

			if (Trimmed == TEXT("0") || Trimmed == TEXT("false") || Trimmed == TEXT("no"))
			{
				OutValue = false;
				return true;
			}
		}

		return false;
	}

	int32 GetPositiveQueryIntOrDefault(const FHttpServerRequest& Request, const FString& Key, int32 DefaultValue = 0)
	{
		if (const FString* Value = Request.QueryParams.Find(Key))
		{
			int32 Parsed = 0;
			if (FDefaultValueHelper::ParseInt(Value->TrimStartAndEnd(), Parsed) && Parsed > 0)
			{
				return Parsed;
			}
		}

		return DefaultValue;
	}

	int64 GetNonNegativeQueryInt64OrDefault(const FHttpServerRequest& Request, const FString& Key, int64 DefaultValue = 0)
	{
		if (const FString* Value = Request.QueryParams.Find(Key))
		{
			const FString Trimmed = Value->TrimStartAndEnd();
			if (!Trimmed.IsEmpty() && Trimmed.IsNumeric())
			{
				const int64 Parsed = FCString::Atoi64(*Trimmed);
				if (Parsed >= 0)
				{
					return Parsed;
				}
			}
		}

		return DefaultValue;
	}

	FString ReadJsonString(const TSharedRef<FJsonObject>& Json, const FString& FieldName, const FString& DefaultValue = TEXT(""))
	{
		FString Value;
		return Json->TryGetStringField(FieldName, Value) ? Value : DefaultValue;
	}

	int32 ReadJsonInt(const TSharedRef<FJsonObject>& Json, const FString& FieldName, int32 DefaultValue = 0)
	{
		double Number = static_cast<double>(DefaultValue);
		return Json->TryGetNumberField(FieldName, Number) ? static_cast<int32>(FMath::RoundToInt(Number)) : DefaultValue;
	}

	bool ReadJsonBool(const TSharedRef<FJsonObject>& Json, const FString& FieldName, bool DefaultValue = false)
	{
		bool Value = DefaultValue;
		return Json->TryGetBoolField(FieldName, Value) ? Value : DefaultValue;
	}

	bool HasActiveGameWorldWithPlayerController()
	{
		if (GEngine == nullptr)
		{
			return false;
		}

		for (const FWorldContext& WorldContext : GEngine->GetWorldContexts())
		{
			UWorld* World = WorldContext.World();
			if (World == nullptr || !World->IsGameWorld())
			{
				continue;
			}

			if (World->GetFirstPlayerController() != nullptr)
			{
				return true;
			}
		}

		return false;
	}

	bool RunOnGameThreadSync(const TFunction<void()>& InTask)
	{
		if (IsInGameThread())
		{
			InTask();
			return true;
		}

		FEvent* CompletionEvent = FPlatformProcess::GetSynchEventFromPool(false);
		if (CompletionEvent == nullptr)
		{
			return false;
		}

		AsyncTask(ENamedThreads::GameThread, [InTask, CompletionEvent]()
		{
			InTask();
			CompletionEvent->Trigger();
		});

		CompletionEvent->Wait();
		FPlatformProcess::ReturnSynchEventToPool(CompletionEvent);
		return true;
	}

	struct FEditorAutoPlayResult
	{
		bool bRequested = false;
		bool bReady = false;
		FString ErrorCode;
		FString ErrorMessage;
	};

	FEditorAutoPlayResult TryEnsureEditorPlayReady(bool bEnableAutoPlay, double WaitSeconds)
	{
		FEditorAutoPlayResult Result;
		Result.bReady = false;

		bool bAlreadyReady = false;
		if (!RunOnGameThreadSync([&bAlreadyReady]()
		{
			bAlreadyReady = HasActiveGameWorldWithPlayerController();
		}))
		{
			Result.ErrorCode = TEXT("auto_play_dispatch_failed");
			Result.ErrorMessage = TEXT("Failed to dispatch readiness check to game thread.");
			return Result;
		}
		if (bAlreadyReady)
		{
			Result.bReady = true;
			return Result;
		}

		if (!bEnableAutoPlay)
		{
			Result.ErrorCode = TEXT("auto_play_disabled");
			Result.ErrorMessage = TEXT("No active game world. Enable auto_play_editor or start PIE manually.");
			return Result;
		}

#if WITH_EDITOR
		if (!RunOnGameThreadSync([&Result]()
		{
			if (GEditor == nullptr)
			{
				Result.ErrorCode = TEXT("editor_unavailable");
				Result.ErrorMessage = TEXT("GEditor is not available.");
				return;
			}

			if (!GEditor->IsPlaySessionInProgress())
			{
				FRequestPlaySessionParams PlayParams;
				PlayParams.SessionDestination = EPlaySessionDestinationType::InProcess;
				PlayParams.WorldType = EPlaySessionWorldType::PlayInEditor;
				GEditor->RequestPlaySession(PlayParams);
				Result.bRequested = true;
			}
			else
			{
				Result.bRequested = true;
			}
		}))
		{
			Result.ErrorCode = TEXT("auto_play_dispatch_failed");
			Result.ErrorMessage = TEXT("Failed to dispatch auto play request to game thread.");
			return Result;
		}
#else
		Result.ErrorCode = TEXT("auto_play_unsupported");
		Result.ErrorMessage = TEXT("Auto play is only supported when built with editor modules.");
		return Result;
#endif

		const double Deadline = FPlatformTime::Seconds() + FMath::Clamp(WaitSeconds, 0.0, 60.0);
		while (FPlatformTime::Seconds() <= Deadline)
		{
			bool bNowReady = false;
			if (!RunOnGameThreadSync([&bNowReady]()
			{
				bNowReady = HasActiveGameWorldWithPlayerController();
			}))
			{
				Result.ErrorCode = TEXT("auto_play_dispatch_failed");
				Result.ErrorMessage = TEXT("Failed to poll game world readiness on game thread.");
				return Result;
			}

			if (bNowReady)
			{
				Result.bReady = true;
				Result.ErrorCode.Reset();
				Result.ErrorMessage.Reset();
				return Result;
			}

			FPlatformProcess::Sleep(0.05f);
		}

		Result.ErrorCode = TEXT("auto_play_timeout");
		Result.ErrorMessage = TEXT("Timed out waiting for PIE game world readiness.");
		return Result;
	}

	bool SendAll(FSocket* Socket, const uint8* Data, int32 Size)
	{
		if (Socket == nullptr || Data == nullptr || Size <= 0)
		{
			return false;
		}

		int32 TotalSent = 0;
		while (TotalSent < Size)
		{
			int32 Sent = 0;
			if (!Socket->Send(Data + TotalSent, Size - TotalSent, Sent) || Sent <= 0)
			{
				return false;
			}

			TotalSent += Sent;
		}

		return true;
	}

	ISocketSubsystem* GetSocketSubsystem()
	{
		FSocketSubsystemModule& SocketSubsystemModule = FModuleManager::LoadModuleChecked<FSocketSubsystemModule>(TEXT("Sockets"));
		return SocketSubsystemModule.GetSocketSubsystem(PLATFORM_SOCKETSUBSYSTEM);
	}

	bool ReceiveHttpHeader(FSocket* Socket, FString& OutRequest, double TimeoutSeconds = 2.0)
	{
		OutRequest.Reset();

		if (Socket == nullptr)
		{
			return false;
		}

		TArray<uint8> Buffer;
		Buffer.Reserve(2048);
		const double StartTime = FPlatformTime::Seconds();

		while ((FPlatformTime::Seconds() - StartTime) < TimeoutSeconds)
		{
			uint32 PendingData = 0;
			if (Socket->HasPendingData(PendingData) && PendingData > 0)
			{
				const int32 BytesToRead = FMath::Min<int32>(static_cast<int32>(PendingData), 1024);
				TArray<uint8> Chunk;
				Chunk.SetNumUninitialized(BytesToRead);

				int32 BytesRead = 0;
				if (!Socket->Recv(Chunk.GetData(), Chunk.Num(), BytesRead) || BytesRead <= 0)
				{
					return false;
				}

				Buffer.Append(Chunk.GetData(), BytesRead);
				if (Buffer.Num() > 8192)
				{
					return false;
				}

				const FUTF8ToTCHAR Converter(reinterpret_cast<const UTF8CHAR*>(Buffer.GetData()), Buffer.Num());
				OutRequest = FString(Converter.Length(), Converter.Get());
				if (OutRequest.Contains(TEXT("\r\n\r\n")))
				{
					return true;
				}
			}
			else
			{
				Socket->Wait(ESocketWaitConditions::WaitForRead, FTimespan::FromMilliseconds(25));
			}
		}

		return false;
	}

	FString ExtractHeaderValue(const FString& RequestText, const FString& HeaderName)
	{
		TArray<FString> Lines;
		RequestText.ParseIntoArrayLines(Lines, false);

		const FString HeaderPrefix = HeaderName.TrimStartAndEnd().ToLower() + TEXT(":");
		for (const FString& Line : Lines)
		{
			const FString Trimmed = Line.TrimStartAndEnd();
			const FString Lowered = Trimmed.ToLower();
			if (Lowered.StartsWith(HeaderPrefix))
			{
				return Trimmed.Mid(HeaderPrefix.Len()).TrimStartAndEnd();
			}
		}

		return FString();
	}

	FString ExtractRequestTarget(const FString& RequestLine)
	{
		TArray<FString> Tokens;
		RequestLine.ParseIntoArrayWS(Tokens);
		if (Tokens.Num() >= 2)
		{
			return Tokens[1].TrimStartAndEnd();
		}

		return FString();
	}

	FString BuildWebSocketAcceptKey(const FString& ClientKey)
	{
		const FString Combined = ClientKey.TrimStartAndEnd() + WebSocketMagicGuid;
		const FTCHARToUTF8 Utf8(*Combined);
		uint8 Digest[FSHA1::DigestSize];
		FSHA1::HashBuffer(Utf8.Get(), Utf8.Length(), Digest);
		return FBase64::Encode(Digest, UE_ARRAY_COUNT(Digest));
	}

	TArray<uint8> BuildWebSocketTextFrame(const FString& Message)
	{
		const FTCHARToUTF8 Utf8(*Message);
		const int32 PayloadSize = Utf8.Length();
		TArray<uint8> Frame;
		Frame.Reserve(PayloadSize + 10);
		Frame.Add(0x81);

		if (PayloadSize <= 125)
		{
			Frame.Add(static_cast<uint8>(PayloadSize));
		}
		else if (PayloadSize <= 65535)
		{
			Frame.Add(126);
			Frame.Add(static_cast<uint8>((PayloadSize >> 8) & 0xFF));
			Frame.Add(static_cast<uint8>(PayloadSize & 0xFF));
		}
		else
		{
			Frame.Add(127);
			const uint64 ExtendedLength = static_cast<uint64>(PayloadSize);
			for (int32 Shift = 56; Shift >= 0; Shift -= 8)
			{
				Frame.Add(static_cast<uint8>((ExtendedLength >> Shift) & 0xFF));
			}
		}

		const int32 DataOffset = Frame.Num();
		Frame.AddUninitialized(PayloadSize);
		FMemory::Memcpy(Frame.GetData() + DataOffset, Utf8.Get(), PayloadSize);
		return Frame;
	}

	TSharedRef<FJsonObject> BuildEventJsonObject(const FGameTestEventRecord& Event)
	{
		TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
		Json->SetStringField(TEXT("session_id"), Event.SessionId);
		Json->SetStringField(TEXT("type"), Event.Type);
		Json->SetNumberField(TEXT("sequence_id"), static_cast<double>(Event.SequenceId));
		Json->SetStringField(TEXT("time"), Event.TimestampUtc.ToIso8601());
		Json->SetStringField(TEXT("trace_id"), Event.TraceId);

		if (Event.Payload.IsValid())
		{
			Json->SetObjectField(TEXT("payload"), Event.Payload);
		}

		return Json;
	}

	FString BuildEventJsonString(const FGameTestEventRecord& Event)
	{
		FString Output;
		const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
		FJsonSerializer::Serialize(BuildEventJsonObject(Event), Writer);
		return Output;
	}

	struct FViewportScreenshotCaptureResult
	{
		bool bSucceeded = false;
		bool bHasViewportState = false;
		bool bIsMinimized = false;
		bool bIsOccluded = false;
		bool bIsFocused = false;
		int32 ViewportWidth = 0;
		int32 ViewportHeight = 0;
		FString CaptureSource;
		FString ErrorCode;
		FString ErrorMessage;
		TArray<FColor> SourcePixels;
	};

	struct FViewportScreenshotDispatchState : public TSharedFromThis<FViewportScreenshotDispatchState, ESPMode::ThreadSafe>
	{
		FEvent* CompletionEvent = nullptr;
		FViewportScreenshotCaptureResult Result;

		~FViewportScreenshotDispatchState()
		{
			if (CompletionEvent != nullptr)
			{
				FPlatformProcess::ReturnSynchEventToPool(CompletionEvent);
				CompletionEvent = nullptr;
			}
		}
	};

	TSharedRef<FJsonObject> BuildViewportStateJson(const FViewportScreenshotCaptureResult& CaptureResult)
	{
		TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
		Json->SetBoolField(TEXT("is_minimized"), CaptureResult.bIsMinimized);
		Json->SetBoolField(TEXT("is_occluded"), CaptureResult.bIsOccluded);
		Json->SetBoolField(TEXT("is_focused"), CaptureResult.bIsFocused);
		Json->SetNumberField(TEXT("viewport_width"), static_cast<double>(CaptureResult.ViewportWidth));
		Json->SetNumberField(TEXT("viewport_height"), static_cast<double>(CaptureResult.ViewportHeight));
		Json->SetStringField(TEXT("capture_source"), CaptureResult.CaptureSource);
		return Json;
	}

	bool ResizeViewportPixels(
		const TArray<FColor>& SourcePixels,
		int32 SourceWidth,
		int32 SourceHeight,
		int32 TargetWidth,
		int32 TargetHeight,
		TArray<FColor>& OutPixels)
	{
		if (SourcePixels.Num() <= 0 || SourceWidth <= 0 || SourceHeight <= 0 || TargetWidth <= 0 || TargetHeight <= 0)
		{
			return false;
		}

		const int64 TargetPixelCount = static_cast<int64>(TargetWidth) * static_cast<int64>(TargetHeight);
		if (TargetPixelCount <= 0 || TargetPixelCount > static_cast<int64>(MAX_int32))
		{
			return false;
		}

		if (SourceWidth == TargetWidth && SourceHeight == TargetHeight)
		{
			OutPixels = SourcePixels;
			return true;
		}

		OutPixels.SetNumUninitialized(static_cast<int32>(TargetPixelCount));

		auto SamplePixel = [&SourcePixels, SourceWidth, SourceHeight](int32 X, int32 Y) -> const FColor&
		{
			const int32 ClampedX = FMath::Clamp(X, 0, SourceWidth - 1);
			const int32 ClampedY = FMath::Clamp(Y, 0, SourceHeight - 1);
			return SourcePixels[ClampedY * SourceWidth + ClampedX];
		};

		auto LerpColor = [](const FColor& A, const FColor& B, double Alpha) -> FColor
		{
			const double ClampedAlpha = FMath::Clamp(Alpha, 0.0, 1.0);
			FLinearColor LinearA(A);
			FLinearColor LinearB(B);
			FLinearColor LinearResult;
			LinearResult.R = FMath::Lerp(LinearA.R, LinearB.R, static_cast<float>(ClampedAlpha));
			LinearResult.G = FMath::Lerp(LinearA.G, LinearB.G, static_cast<float>(ClampedAlpha));
			LinearResult.B = FMath::Lerp(LinearA.B, LinearB.B, static_cast<float>(ClampedAlpha));
			LinearResult.A = FMath::Lerp(LinearA.A, LinearB.A, static_cast<float>(ClampedAlpha));
			return LinearResult.ToFColor(false);
		};

		const double XScale = (TargetWidth > 1) ? static_cast<double>(SourceWidth - 1) / static_cast<double>(TargetWidth - 1) : 0.0;
		const double YScale = (TargetHeight > 1) ? static_cast<double>(SourceHeight - 1) / static_cast<double>(TargetHeight - 1) : 0.0;

		for (int32 TargetY = 0; TargetY < TargetHeight; ++TargetY)
		{
			const double SourceY = YScale * static_cast<double>(TargetY);
			const int32 Y0 = FMath::Clamp(FMath::FloorToInt(SourceY), 0, SourceHeight - 1);
			const int32 Y1 = FMath::Clamp(Y0 + 1, 0, SourceHeight - 1);
			const double YAlpha = SourceY - static_cast<double>(Y0);

			for (int32 TargetX = 0; TargetX < TargetWidth; ++TargetX)
			{
				const double SourceX = XScale * static_cast<double>(TargetX);
				const int32 X0 = FMath::Clamp(FMath::FloorToInt(SourceX), 0, SourceWidth - 1);
				const int32 X1 = FMath::Clamp(X0 + 1, 0, SourceWidth - 1);
				const double XAlpha = SourceX - static_cast<double>(X0);

				const FColor TopLeft = SamplePixel(X0, Y0);
				const FColor TopRight = SamplePixel(X1, Y0);
				const FColor BottomLeft = SamplePixel(X0, Y1);
				const FColor BottomRight = SamplePixel(X1, Y1);

				const FColor Top = LerpColor(TopLeft, TopRight, XAlpha);
				const FColor Bottom = LerpColor(BottomLeft, BottomRight, XAlpha);
				OutPixels[TargetY * TargetWidth + TargetX] = LerpColor(Top, Bottom, YAlpha);
			}
		}

		return true;
	}

	bool TryCaptureViewportPixelsOnGameThread(FViewportScreenshotCaptureResult& OutResult)
	{
		OutResult = FViewportScreenshotCaptureResult();

		if (GEngine == nullptr)
		{
			OutResult.ErrorCode = TEXT("capture_unavailable");
			OutResult.ErrorMessage = TEXT("GEngine is not available.");
			return false;
		}

		for (const FWorldContext& WorldContext : GEngine->GetWorldContexts())
		{
			UWorld* World = WorldContext.World();
			if (World == nullptr || !World->IsGameWorld() || World->GetFirstPlayerController() == nullptr)
			{
				continue;
			}

			UGameViewportClient* GameViewportClient = WorldContext.GameViewport;
			if (GameViewportClient == nullptr)
			{
				GameViewportClient = GEngine->GameViewport;
			}

			FViewport* Viewport = (GameViewportClient != nullptr) ? GameViewportClient->Viewport : nullptr;
			if (Viewport == nullptr)
			{
				continue;
			}

			OutResult.bHasViewportState = true;
			OutResult.CaptureSource = (WorldContext.WorldType == EWorldType::PIE) ? TEXT("pie_viewport") : TEXT("game_viewport");
			OutResult.ViewportWidth = Viewport->GetSizeXY().X;
			OutResult.ViewportHeight = Viewport->GetSizeXY().Y;
			OutResult.bIsFocused = Viewport->HasFocus();
			OutResult.bIsOccluded = !Viewport->IsForegroundWindow();

			if (FSceneViewport* SceneViewport = static_cast<FSceneViewport*>(Viewport))
			{
				TSharedPtr<SWindow> ViewportWindow = SceneViewport->FindWindow();
				OutResult.bIsMinimized = ViewportWindow.IsValid() && ViewportWindow->IsWindowMinimized();
			}

			if (OutResult.bIsMinimized)
			{
				OutResult.ErrorCode = TEXT("viewport_minimized");
				OutResult.ErrorMessage = TEXT("The target viewport is minimized.");
				return false;
			}

			if (OutResult.ViewportWidth <= 0 || OutResult.ViewportHeight <= 0)
			{
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("The target viewport size is invalid.");
				return false;
			}

			const int64 PixelCount64 = static_cast<int64>(OutResult.ViewportWidth) * static_cast<int64>(OutResult.ViewportHeight);
			if (PixelCount64 <= 0 || PixelCount64 > static_cast<int64>(MAX_int32))
			{
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("The target viewport is too large to capture.");
				return false;
			}

			TArray<FColor> Pixels;
			Pixels.Reserve(static_cast<int32>(PixelCount64));

			FReadSurfaceDataFlags ReadFlags(RCM_UNorm);
			ReadFlags.SetLinearToGamma(false);

			if (!Viewport->ReadPixels(Pixels, ReadFlags, FIntRect(0, 0, OutResult.ViewportWidth, OutResult.ViewportHeight)))
			{
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("Failed to read pixels from the target viewport.");
				return false;
			}

			if (Pixels.Num() != static_cast<int32>(PixelCount64))
			{
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("The viewport returned an unexpected pixel count.");
				return false;
			}

			OutResult.SourcePixels = MoveTemp(Pixels);
			OutResult.bSucceeded = true;
			return true;
		}

		OutResult.ErrorCode = TEXT("capture_unavailable");
		OutResult.ErrorMessage = TEXT("No active game or PIE viewport could be found.");
		return false;
	}

	bool TryCaptureSceneViewPixelsOnGameThread(FViewportScreenshotCaptureResult& OutResult)
	{
		OutResult = FViewportScreenshotCaptureResult();

		if (GEngine == nullptr)
		{
			OutResult.ErrorCode = TEXT("capture_unavailable");
			OutResult.ErrorMessage = TEXT("GEngine is not available.");
			return false;
		}

		for (const FWorldContext& WorldContext : GEngine->GetWorldContexts())
		{
			UWorld* World = WorldContext.World();
			if (World == nullptr || !World->IsGameWorld())
			{
				continue;
			}

			APlayerController* PlayerController = World->GetFirstPlayerController();
			if (PlayerController == nullptr)
			{
				continue;
			}

			int32 CaptureWidth = 1280;
			int32 CaptureHeight = 720;
			bool bIsMinimized = false;
			bool bIsFocused = false;
			bool bIsOccluded = false;

			UGameViewportClient* GameViewportClient = WorldContext.GameViewport;
			if (GameViewportClient == nullptr)
			{
				GameViewportClient = GEngine->GameViewport;
			}
			FViewport* Viewport = (GameViewportClient != nullptr) ? GameViewportClient->Viewport : nullptr;
			if (Viewport != nullptr)
			{
				const FIntPoint ViewportSize = Viewport->GetSizeXY();
				CaptureWidth = FMath::Max(1, ViewportSize.X);
				CaptureHeight = FMath::Max(1, ViewportSize.Y);
				bIsFocused = Viewport->HasFocus();
				bIsOccluded = !Viewport->IsForegroundWindow();

				if (FSceneViewport* SceneViewport = static_cast<FSceneViewport*>(Viewport))
				{
					TSharedPtr<SWindow> ViewportWindow = SceneViewport->FindWindow();
					bIsMinimized = ViewportWindow.IsValid() && ViewportWindow->IsWindowMinimized();
				}
			}

			OutResult.bHasViewportState = true;
			OutResult.bIsMinimized = bIsMinimized;
			OutResult.bIsFocused = bIsFocused;
			OutResult.bIsOccluded = bIsOccluded;
			OutResult.ViewportWidth = CaptureWidth;
			OutResult.ViewportHeight = CaptureHeight;
			OutResult.CaptureSource = (WorldContext.WorldType == EWorldType::PIE) ? TEXT("scene_capture_2d_pie") : TEXT("scene_capture_2d_game");

			if (OutResult.bIsMinimized)
			{
				OutResult.ErrorCode = TEXT("viewport_minimized");
				OutResult.ErrorMessage = TEXT("The target viewport is minimized.");
				return false;
			}

			FVector ViewLocation = FVector::ZeroVector;
			FRotator ViewRotation = FRotator::ZeroRotator;
			bool bHasViewTransform = false;
			if (APlayerCameraManager* CameraManager = PlayerController->PlayerCameraManager)
			{
				CameraManager->GetCameraViewPoint(ViewLocation, ViewRotation);
				bHasViewTransform = true;
			}

			if (!bHasViewTransform)
			{
				if (APawn* Pawn = PlayerController->GetPawn())
				{
					ViewLocation = Pawn->GetActorLocation();
					ViewRotation = PlayerController->GetControlRotation();
					bHasViewTransform = true;
				}
			}

			if (!bHasViewTransform)
			{
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("Could not resolve player camera transform.");
				return false;
			}

			FActorSpawnParameters SpawnParams;
			SpawnParams.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			SpawnParams.ObjectFlags |= RF_Transient;
			ASceneCapture2D* CaptureActor = World->SpawnActor<ASceneCapture2D>(ASceneCapture2D::StaticClass(), ViewLocation, ViewRotation, SpawnParams);
			if (CaptureActor == nullptr)
			{
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("Failed to spawn SceneCapture2D actor.");
				return false;
			}

			auto DestroyCaptureActor = [&CaptureActor]()
			{
				if (CaptureActor != nullptr)
				{
					CaptureActor->Destroy();
					CaptureActor = nullptr;
				}
			};

			USceneCaptureComponent2D* CaptureComponent = CaptureActor->GetCaptureComponent2D();
			if (CaptureComponent == nullptr)
			{
				DestroyCaptureActor();
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("SceneCapture2D component is not available.");
				return false;
			}

			UTextureRenderTarget2D* RenderTarget = NewObject<UTextureRenderTarget2D>(CaptureActor, NAME_None, RF_Transient);
			if (RenderTarget == nullptr)
			{
				DestroyCaptureActor();
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("Failed to allocate render target for scene capture.");
				return false;
			}

			RenderTarget->bAutoGenerateMips = false;
			RenderTarget->ClearColor = FLinearColor::Black;
			RenderTarget->InitCustomFormat(CaptureWidth, CaptureHeight, PF_B8G8R8A8, false);
			RenderTarget->UpdateResourceImmediate(true);

			CaptureComponent->TextureTarget = RenderTarget;
			CaptureComponent->CaptureSource = ESceneCaptureSource::SCS_FinalColorLDR;
			CaptureComponent->bCaptureEveryFrame = false;
			CaptureComponent->bCaptureOnMovement = false;
			CaptureComponent->SetWorldLocationAndRotation(ViewLocation, ViewRotation);
			if (APlayerCameraManager* CameraManager = PlayerController->PlayerCameraManager)
			{
				CaptureComponent->FOVAngle = CameraManager->GetFOVAngle();
			}

			CaptureComponent->CaptureScene();
			FlushRenderingCommands();

			FTextureRenderTargetResource* RenderTargetResource = RenderTarget->GameThread_GetRenderTargetResource();
			if (RenderTargetResource == nullptr)
			{
				DestroyCaptureActor();
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("Render target resource is not available.");
				return false;
			}

			TArray<FColor> Pixels;
			FReadSurfaceDataFlags ReadFlags(RCM_UNorm);
			ReadFlags.SetLinearToGamma(false);
			if (!RenderTargetResource->ReadPixels(Pixels, ReadFlags))
			{
				DestroyCaptureActor();
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("Failed to read pixels from scene capture render target.");
				return false;
			}

			const int64 ExpectedPixelCount = static_cast<int64>(CaptureWidth) * static_cast<int64>(CaptureHeight);
			if (Pixels.Num() != static_cast<int32>(ExpectedPixelCount))
			{
				DestroyCaptureActor();
				OutResult.ErrorCode = TEXT("capture_unavailable");
				OutResult.ErrorMessage = TEXT("Scene capture returned an unexpected pixel count.");
				return false;
			}

			OutResult.SourcePixels = MoveTemp(Pixels);
			OutResult.bSucceeded = true;

			DestroyCaptureActor();
			return true;
		}

		OutResult.ErrorCode = TEXT("capture_unavailable");
		OutResult.ErrorMessage = TEXT("No active game or PIE world with a player controller could be found.");
		return false;
	}

	bool TryCaptureViewportScreenshot(FViewportScreenshotCaptureResult& OutResult, double TimeoutSeconds)
	{
		if (IsInGameThread())
		{
			FViewportScreenshotCaptureResult SceneCaptureResult;
			if (TryCaptureSceneViewPixelsOnGameThread(SceneCaptureResult))
			{
				OutResult = MoveTemp(SceneCaptureResult);
				return true;
			}

			FViewportScreenshotCaptureResult ViewportCaptureResult;
			if (TryCaptureViewportPixelsOnGameThread(ViewportCaptureResult))
			{
				OutResult = MoveTemp(ViewportCaptureResult);
				return true;
			}

			OutResult = MoveTemp(SceneCaptureResult);
			if (OutResult.ErrorCode.IsEmpty() && !ViewportCaptureResult.ErrorCode.IsEmpty())
			{
				OutResult = MoveTemp(ViewportCaptureResult);
			}
			return false;
		}

		TSharedRef<FViewportScreenshotDispatchState, ESPMode::ThreadSafe> DispatchState = MakeShared<FViewportScreenshotDispatchState, ESPMode::ThreadSafe>();
		DispatchState->CompletionEvent = FPlatformProcess::GetSynchEventFromPool(false);
		if (DispatchState->CompletionEvent == nullptr)
		{
			OutResult.ErrorCode = TEXT("capture_unavailable");
			OutResult.ErrorMessage = TEXT("Failed to allocate a synchronization event.");
			return false;
		}

		AsyncTask(ENamedThreads::GameThread, [DispatchState]()
		{
			TryCaptureViewportScreenshot(DispatchState->Result, 0.0);
			if (DispatchState->CompletionEvent != nullptr)
			{
				DispatchState->CompletionEvent->Trigger();
			}
		});

		const bool bCompleted = DispatchState->CompletionEvent->Wait(FTimespan::FromSeconds(FMath::Max(0.0, TimeoutSeconds)));
		if (!bCompleted)
		{
			OutResult.ErrorCode = TEXT("capture_timeout");
			OutResult.ErrorMessage = TEXT("Timed out while waiting for the viewport capture to complete.");
			return false;
		}

		OutResult = MoveTemp(DispatchState->Result);
		return OutResult.bSucceeded;
	}

	bool EncodeScreenshotToBase64Jpeg(
		const TArray<FColor>& SourcePixels,
		int32 SourceWidth,
		int32 SourceHeight,
		int32 TargetHeight,
		bool bPreserveAspectRatio,
		int32 JpegQuality,
		FString& OutImageBase64,
		int32& OutWidth,
		int32& OutHeight,
		FString& OutErrorCode,
		FString& OutErrorMessage)
	{
		OutImageBase64.Reset();
		OutWidth = 0;
		OutHeight = 0;
		OutErrorCode.Reset();
		OutErrorMessage.Reset();

		if (SourcePixels.Num() <= 0 || SourceWidth <= 0 || SourceHeight <= 0 || TargetHeight <= 0)
		{
			OutErrorCode = TEXT("capture_unavailable");
			OutErrorMessage = TEXT("Invalid source or target dimensions for screenshot encoding.");
			return false;
		}

		const int32 ClampedQuality = FMath::Clamp(JpegQuality, 1, 100);
		const int32 OutputHeight = FMath::Max(1, TargetHeight);
		const int32 OutputWidth = bPreserveAspectRatio
			? FMath::Max(1, FMath::RoundToInt(static_cast<double>(SourceWidth) * (static_cast<double>(OutputHeight) / static_cast<double>(SourceHeight))))
			: FMath::Max(1, SourceWidth);

		TArray<FColor> OutputPixels;
		if (!ResizeViewportPixels(SourcePixels, SourceWidth, SourceHeight, OutputWidth, OutputHeight, OutputPixels))
		{
			OutErrorCode = TEXT("capture_unavailable");
			OutErrorMessage = TEXT("Failed to resize the screenshot.");
			return false;
		}

		IImageWrapperModule& ImageWrapperModule = FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
		TSharedPtr<IImageWrapper> ImageWrapper = ImageWrapperModule.CreateImageWrapper(EImageFormat::JPEG);
		if (!ImageWrapper.IsValid())
		{
			OutErrorCode = TEXT("capture_unavailable");
			OutErrorMessage = TEXT("Failed to create a JPEG image wrapper.");
			return false;
		}

		if (!ImageWrapper->SetRaw(
				OutputPixels.GetData(),
				static_cast<int64>(OutputPixels.Num()) * static_cast<int64>(sizeof(FColor)),
				OutputWidth,
				OutputHeight,
				ERGBFormat::BGRA,
				8))
		{
			OutErrorCode = TEXT("capture_unavailable");
			OutErrorMessage = TEXT("Failed to prepare the screenshot for JPEG encoding.");
			return false;
		}

		const TArray64<uint8> CompressedBytes = ImageWrapper->GetCompressed(ClampedQuality);
		if (CompressedBytes.Num() <= 0)
		{
			OutErrorCode = TEXT("capture_unavailable");
			OutErrorMessage = TEXT("JPEG compression returned no data.");
			return false;
		}

		OutImageBase64 = FBase64::Encode(
			reinterpret_cast<const uint8*>(CompressedBytes.GetData()),
			static_cast<int32>(CompressedBytes.Num()));
		OutWidth = OutputWidth;
		OutHeight = OutputHeight;
		return true;
	}
}

struct FGameTestWebSocketClient
{
	FSocket* Socket = nullptr;
	FString RemoteAddress;
	FString RequestTarget;
};

class FGameTestWebSocketServer final : public FRunnable
{
public:
	explicit FGameTestWebSocketServer(uint16 InPort)
		: Port(InPort)
		, ListenSocket(nullptr)
		, Thread(nullptr)
		, bStopping(false)
	{
	}

	~FGameTestWebSocketServer()
	{
		Shutdown();
	}

	bool Start()
	{
		if (Thread != nullptr)
		{
			return true;
		}

		ISocketSubsystem* SocketSubsystem = GetSocketSubsystem();
		if (SocketSubsystem == nullptr)
		{
			return false;
		}

		ListenSocket = SocketSubsystem->CreateSocket(NAME_Stream, TEXT("GameTestWebSocketListener"), false);
		if (ListenSocket == nullptr)
		{
			return false;
		}

		ListenSocket->SetReuseAddr(true);
		ListenSocket->SetNoDelay(true);
		ListenSocket->SetNonBlocking(true);

		TSharedRef<FInternetAddr> BindAddress = SocketSubsystem->CreateInternetAddr();
		BindAddress->SetAnyAddress();
		BindAddress->SetPort(Port);

		if (!ListenSocket->Bind(*BindAddress) || !ListenSocket->Listen(16))
		{
			SocketSubsystem->DestroySocket(ListenSocket);
			ListenSocket = nullptr;
			return false;
		}

		Thread = FRunnableThread::Create(this, TEXT("GameTestWebSocketServer"), 64 * 1024, TPri_Normal);
		if (Thread == nullptr)
		{
			ListenSocket->Close();
			SocketSubsystem->DestroySocket(ListenSocket);
			ListenSocket = nullptr;
			return false;
		}

		return true;
	}

	void Shutdown()
	{
		bStopping = true;

		if (Thread != nullptr)
		{
			Thread->Kill(true);
			delete Thread;
			Thread = nullptr;
		}

		ISocketSubsystem* SocketSubsystem = GetSocketSubsystem();
		if (ListenSocket != nullptr)
		{
			ListenSocket->Close();
			SocketSubsystem->DestroySocket(ListenSocket);
			ListenSocket = nullptr;
		}

		CleanupClients();
	}

	void BroadcastEvent(const FGameTestEventRecord& Event)
	{
		const FString Message = BuildEventJsonString(Event);
		const TArray<uint8> Frame = BuildWebSocketTextFrame(Message);

		TArray<TSharedPtr<FGameTestWebSocketClient, ESPMode::ThreadSafe>> Snapshot;
		{
			FScopeLock Lock(&ClientLock);
			Snapshot = Clients;
		}

		TArray<FSocket*> FailedSockets;
		for (const TSharedPtr<FGameTestWebSocketClient, ESPMode::ThreadSafe>& Client : Snapshot)
		{
			if (!Client.IsValid() || Client->Socket == nullptr || !SendAll(Client->Socket, Frame.GetData(), Frame.Num()))
			{
				FailedSockets.Add(Client.IsValid() ? Client->Socket : nullptr);
			}
		}

		if (FailedSockets.Num() > 0)
		{
			FScopeLock Lock(&ClientLock);
			Clients.RemoveAll([&FailedSockets](const TSharedPtr<FGameTestWebSocketClient, ESPMode::ThreadSafe>& Client)
			{
				return !Client.IsValid() || FailedSockets.Contains(Client->Socket);
			});
		}
	}

	bool IsRunning() const
	{
		return Thread != nullptr && !bStopping;
	}

	uint16 GetPort() const
	{
		return Port;
	}

	virtual bool Init() override
	{
		return true;
	}

	virtual uint32 Run() override
	{
		while (!bStopping)
		{
			bool bHasPendingConnection = false;
			if (ListenSocket != nullptr && ListenSocket->WaitForPendingConnection(bHasPendingConnection, FTimespan::FromMilliseconds(100)))
			{
				if (bHasPendingConnection)
				{
					FSocket* ClientSocket = ListenSocket->Accept(TEXT("GameTestWebSocketClient"));
					if (ClientSocket != nullptr)
					{
						if (!AcceptClient(ClientSocket))
						{
							ClientSocket->Close();
							GetSocketSubsystem()->DestroySocket(ClientSocket);
						}
					}
				}
			}
			else
			{
				FPlatformProcess::Sleep(0.01f);
			}
		}

		return 0;
	}

	virtual void Stop() override
	{
		bStopping = true;
	}

	virtual void Exit() override
	{
	}

private:
	bool AcceptClient(FSocket* ClientSocket)
	{
		if (ClientSocket == nullptr)
		{
			return false;
		}

		FString RequestText;
		if (!ReceiveHttpHeader(ClientSocket, RequestText))
		{
			return false;
		}

		TArray<FString> RequestLines;
		RequestText.ParseIntoArrayLines(RequestLines, false);
		if (RequestLines.Num() == 0)
		{
			return false;
		}

		const FString RequestTarget = ExtractRequestTarget(RequestLines[0]);
		const FString ClientKey = ExtractHeaderValue(RequestText, TEXT("Sec-WebSocket-Key"));
		if (ClientKey.IsEmpty())
		{
			return false;
		}

		const FString AcceptKey = BuildWebSocketAcceptKey(ClientKey);
		const FString ResponseText = FString::Printf(
			TEXT("HTTP/1.1 101 Switching Protocols\r\n")
			TEXT("Upgrade: websocket\r\n")
			TEXT("Connection: Upgrade\r\n")
			TEXT("Sec-WebSocket-Accept: %s\r\n")
			TEXT("\r\n"),
			*AcceptKey);

		const FTCHARToUTF8 ResponseUtf8(*ResponseText);
		if (!SendAll(ClientSocket, reinterpret_cast<const uint8*>(ResponseUtf8.Get()), ResponseUtf8.Length()))
		{
			return false;
		}

		ClientSocket->SetNoDelay(true);
		TSharedPtr<FGameTestWebSocketClient, ESPMode::ThreadSafe> Client = MakeShared<FGameTestWebSocketClient, ESPMode::ThreadSafe>();
		Client->Socket = ClientSocket;
		Client->RequestTarget = RequestTarget;

		{
			FScopeLock Lock(&ClientLock);
			Clients.Add(Client);
		}

		return true;
	}

	void CleanupClients()
	{
		ISocketSubsystem* SocketSubsystem = GetSocketSubsystem();
		FScopeLock Lock(&ClientLock);
		for (const TSharedPtr<FGameTestWebSocketClient, ESPMode::ThreadSafe>& Client : Clients)
		{
			if (Client.IsValid() && Client->Socket != nullptr)
			{
				Client->Socket->Close();
				SocketSubsystem->DestroySocket(Client->Socket);
				Client->Socket = nullptr;
			}
		}
		Clients.Reset();
	}

private:
	uint16 Port;
	FSocket* ListenSocket;
	FRunnableThread* Thread;
	TAtomic<bool> bStopping;
	mutable FCriticalSection ClientLock;
	TArray<TSharedPtr<FGameTestWebSocketClient, ESPMode::ThreadSafe>> Clients;
};

FGameTestRemoteServer::FGameTestRemoteServer()
	: ListeningPort(0)
	, WebSocketPort(0)
	, bRunning(false)
	, EventRecorder(256)
	, RuntimeState(10)
{
}

FGameTestRemoteServer::~FGameTestRemoteServer()
{
	Stop();
}

bool FGameTestRemoteServer::Start(uint16 InPort)
{
	if (bRunning)
	{
		return true;
	}

	if (InPort == 0)
	{
		UE_LOG(LogGameTestRemoteServer, Error, TEXT("Failed to start remote server: invalid port 0."));
		return false;
	}

	FHttpServerModule& HttpServerModule = FHttpServerModule::Get();
	HttpRouter = HttpServerModule.GetHttpRouter(InPort, true);
	if (!HttpRouter.IsValid())
	{
		UE_LOG(LogGameTestRemoteServer, Error, TEXT("Failed to start remote server: could not acquire router for port %d."), InPort);
		return false;
	}

	ListeningPort = InPort;

	if (!BindRoutes())
	{
		UE_LOG(LogGameTestRemoteServer, Error, TEXT("Failed to bind remote API routes."));
		UnbindRoutes();
		HttpRouter.Reset();
		ListeningPort = 0;
		return false;
	}

	if (!StartWebSocketStream())
	{
		UE_LOG(LogGameTestRemoteServer, Error, TEXT("Failed to start websocket event stream."));
		UnbindRoutes();
		HttpRouter.Reset();
		ListeningPort = 0;
		WebSocketPort = 0;
		return false;
	}

	EventRecordedHandle = EventRecorder.AddEventRecordedListener(FGameTestEventRecordedDelegate::FDelegate::CreateRaw(this, &FGameTestRemoteServer::HandleRecordedEvent));

	HttpServerModule.StartAllListeners();
	bRunning = true;

	UE_LOG(LogGameTestRemoteServer, Log, TEXT("GameTest remote server started on localhost:%d."), ListeningPort);
	return true;
}

void FGameTestRemoteServer::Stop()
{
	if (!HttpRouter.IsValid() && !bRunning)
	{
		return;
	}

	UnbindRoutes();
	EventRecorder.RemoveEventRecordedListener(EventRecordedHandle);
	EventRecordedHandle.Reset();
	StopWebSocketStream();

	if (bRunning)
	{
		if (FHttpServerModule* HttpServerModule = FModuleManager::GetModulePtr<FHttpServerModule>(TEXT("HTTPServer")))
		{
			HttpServerModule->StopAllListeners();
		}
		else
		{
			UE_LOG(LogGameTestRemoteServer, Verbose, TEXT("HTTPServer module already unloaded. Skip StopAllListeners during shutdown."));
		}
	}

	bRunning = false;
	ListeningPort = 0;
	WebSocketPort = 0;
	HttpRouter.Reset();

	UE_LOG(LogGameTestRemoteServer, Log, TEXT("GameTest remote server stopped."));
}

bool FGameTestRemoteServer::IsRunning() const
{
	return bRunning;
}

uint16 FGameTestRemoteServer::GetPort() const
{
	return ListeningPort;
}

bool FGameTestRemoteServer::BindRoutes()
{
	if (!HttpRouter.IsValid())
	{
		return false;
	}

	RouteHandles.Reset();

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/health")),
		EHttpServerRequestVerbs::VERB_GET,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandleHealth)));

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/capabilities")),
		EHttpServerRequestVerbs::VERB_GET,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandleCapabilities)));

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/session/start")),
		EHttpServerRequestVerbs::VERB_POST,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandleSessionStart)));

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/session/stop")),
		EHttpServerRequestVerbs::VERB_POST,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandleSessionStop)));

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/command/execute")),
		EHttpServerRequestVerbs::VERB_POST,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandleCommandExecute)));

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/capture/screenshot")),
		EHttpServerRequestVerbs::VERB_GET,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandleScreenshotCapture)));

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/state/player")),
		EHttpServerRequestVerbs::VERB_GET,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandlePlayerState)));

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/state/target")),
		EHttpServerRequestVerbs::VERB_GET,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandleTargetState)));

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/state/spatial")),
		EHttpServerRequestVerbs::VERB_GET,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandleSpatialState)));

	RouteHandles.Add(HttpRouter->BindRoute(
		FHttpPath(TEXT("/events")),
		EHttpServerRequestVerbs::VERB_GET,
		FHttpRequestHandler::CreateRaw(this, &FGameTestRemoteServer::HandleEvents)));

	return RouteHandles.Num() == 10;
}

void FGameTestRemoteServer::UnbindRoutes()
{
	if (!HttpRouter.IsValid())
	{
		RouteHandles.Reset();
		return;
	}

	for (const FHttpRouteHandle& RouteHandle : RouteHandles)
	{
		HttpRouter->UnbindRoute(RouteHandle);
	}

	RouteHandles.Reset();
}

bool FGameTestRemoteServer::HandleHealth(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	TSharedRef<FJsonObject> JsonBody = MakeShared<FJsonObject>();
	JsonBody->SetStringField(TEXT("status"), TEXT("ok"));
	JsonBody->SetStringField(TEXT("service"), TEXT("unreal-agent-test-remote-api"));
	JsonBody->SetStringField(TEXT("timestamp"), FDateTime::UtcNow().ToIso8601());
	JsonBody->SetBoolField(TEXT("running"), bRunning);
	JsonBody->SetNumberField(TEXT("port"), static_cast<double>(ListeningPort));
	JsonBody->SetNumberField(TEXT("active_sessions"), static_cast<double>(SessionManager.GetActiveSessionCount()));

	OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
	return true;
}

bool FGameTestRemoteServer::HandleCapabilities(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	TSharedRef<FJsonObject> JsonBody = MakeShared<FJsonObject>();
	JsonBody->SetStringField(TEXT("service"), TEXT("unreal-agent-test-remote-api"));
	JsonBody->SetStringField(TEXT("version"), TEXT("phase2-min"));
	JsonBody->SetStringField(TEXT("timestamp"), FDateTime::UtcNow().ToIso8601());

	TArray<TSharedPtr<FJsonValue>> RouteValues;
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("GET /health")));
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("GET /capabilities")));
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("POST /session/start")));
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("POST /session/stop")));
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("POST /command/execute")));
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("GET /capture/screenshot")));
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("GET /state/player")));
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("GET /state/target")));
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("GET /state/spatial")));
	RouteValues.Add(MakeShared<FJsonValueString>(TEXT("GET /events")));
	JsonBody->SetArrayField(TEXT("routes"), RouteValues);

	TArray<TSharedPtr<FJsonValue>> SessionFields;
	SessionFields.Add(MakeShared<FJsonValueString>(TEXT("session_id")));
	SessionFields.Add(MakeShared<FJsonValueString>(TEXT("run_id")));
	JsonBody->SetArrayField(TEXT("session_fields"), SessionFields);

	TArray<TSharedPtr<FJsonValue>> EventQueryFields;
	EventQueryFields.Add(MakeShared<FJsonValueString>(TEXT("type")));
	EventQueryFields.Add(MakeShared<FJsonValueString>(TEXT("limit")));
	EventQueryFields.Add(MakeShared<FJsonValueString>(TEXT("after_sequence")));
	JsonBody->SetArrayField(TEXT("events_query_fields"), EventQueryFields);

	TArray<TSharedPtr<FJsonValue>> ScreenshotQueryFields;
	ScreenshotQueryFields.Add(MakeShared<FJsonValueString>(TEXT("session_id")));
	ScreenshotQueryFields.Add(MakeShared<FJsonValueString>(TEXT("height")));
	ScreenshotQueryFields.Add(MakeShared<FJsonValueString>(TEXT("preserve_aspect_ratio")));
	ScreenshotQueryFields.Add(MakeShared<FJsonValueString>(TEXT("jpeg_quality")));
	JsonBody->SetArrayField(TEXT("capture_screenshot_query_fields"), ScreenshotQueryFields);

	if (!BuildWebSocketUrl().IsEmpty())
	{
		JsonBody->SetStringField(TEXT("events_websocket_url"), BuildWebSocketUrl());
		JsonBody->SetNumberField(TEXT("events_websocket_port"), static_cast<double>(WebSocketPort));
	}

	OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
	return true;
}

bool FGameTestRemoteServer::HandleSessionStart(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	TSharedPtr<FJsonObject> RequestJson;
	FString ParseError;
	if (!ParseRequestJson(Request, RequestJson, ParseError))
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("invalid_json"), ParseError)));
		return true;
	}

	FString RequestedSessionId;
	FString RequestedRunId;
	RequestJson->TryGetStringField(TEXT("session_id"), RequestedSessionId);
	RequestJson->TryGetStringField(TEXT("run_id"), RequestedRunId);
	const bool bAutoPlayEditor = ReadJsonBool(RequestJson.ToSharedRef(), TEXT("auto_play_editor"), true);
	double AutoPlayWaitSeconds = 15.0;
	if (RequestJson->HasField(TEXT("auto_play_wait_seconds")))
	{
		double RequestedWaitSeconds = AutoPlayWaitSeconds;
		if (RequestJson->TryGetNumberField(TEXT("auto_play_wait_seconds"), RequestedWaitSeconds))
		{
			AutoPlayWaitSeconds = FMath::Clamp(RequestedWaitSeconds, 0.0, 60.0);
		}
	}

	const FGameTestSessionRecord SessionRecord = SessionManager.StartSession(RequestedSessionId, RequestedRunId);
	RuntimeState.EnsureSession(SessionRecord.SessionId);
	const FEditorAutoPlayResult AutoPlayResult = TryEnsureEditorPlayReady(bAutoPlayEditor, AutoPlayWaitSeconds);
	if (!AutoPlayResult.bReady)
	{
		(void)SessionManager.StopSession(SessionRecord.SessionId);
		RuntimeState.RemoveSession(SessionRecord.SessionId);
		EventRecorder.ClearSession(SessionRecord.SessionId);

		TSharedRef<FJsonObject> ErrorJson = MakeErrorJson(
			AutoPlayResult.ErrorCode.IsEmpty() ? TEXT("auto_play_failed") : AutoPlayResult.ErrorCode,
			AutoPlayResult.ErrorMessage.IsEmpty() ? TEXT("Failed to ensure a playable game world.") : AutoPlayResult.ErrorMessage);
		ErrorJson->SetStringField(TEXT("session_id"), SessionRecord.SessionId);
		ErrorJson->SetStringField(TEXT("run_id"), SessionRecord.RunId);
		ErrorJson->SetBoolField(TEXT("auto_play_editor"), bAutoPlayEditor);
		ErrorJson->SetBoolField(TEXT("auto_play_editor_requested"), AutoPlayResult.bRequested);
		ErrorJson->SetBoolField(TEXT("auto_play_editor_ready"), AutoPlayResult.bReady);
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::ServerError, ErrorJson));
		return true;
	}

	TSharedRef<FJsonObject> JsonBody = MakeShared<FJsonObject>();
	JsonBody->SetBoolField(TEXT("accepted"), true);
	JsonBody->SetStringField(TEXT("session_id"), SessionRecord.SessionId);
	JsonBody->SetStringField(TEXT("run_id"), SessionRecord.RunId);
	JsonBody->SetStringField(TEXT("started_at"), SessionRecord.StartedAtUtc.ToIso8601());
	JsonBody->SetNumberField(TEXT("active_sessions"), static_cast<double>(SessionManager.GetActiveSessionCount()));
	JsonBody->SetBoolField(TEXT("auto_play_editor"), bAutoPlayEditor);
	JsonBody->SetBoolField(TEXT("auto_play_editor_requested"), AutoPlayResult.bRequested);
	JsonBody->SetBoolField(TEXT("auto_play_editor_ready"), AutoPlayResult.bReady);

	OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
	return true;
}

bool FGameTestRemoteServer::HandleSessionStop(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	TSharedPtr<FJsonObject> RequestJson;
	FString ParseError;
	if (!ParseRequestJson(Request, RequestJson, ParseError))
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("invalid_json"), ParseError)));
		return true;
	}

	FString SessionId;
	if (!RequestJson->TryGetStringField(TEXT("session_id"), SessionId) || SessionId.IsEmpty())
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("missing_field"), TEXT("session_id is required."))));
		return true;
	}

	const bool bStopped = SessionManager.StopSession(SessionId);

	TSharedRef<FJsonObject> JsonBody = MakeShared<FJsonObject>();
	JsonBody->SetBoolField(TEXT("accepted"), bStopped);
	JsonBody->SetStringField(TEXT("session_id"), SessionId);
	JsonBody->SetNumberField(TEXT("active_sessions"), static_cast<double>(SessionManager.GetActiveSessionCount()));

	if (bStopped)
	{
		EventRecorder.ClearSession(SessionId);
		RuntimeState.RemoveSession(SessionId);
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
	}
	else
	{
		JsonBody->SetStringField(TEXT("error"), TEXT("session_not_found"));
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::NotFound, JsonBody));
	}

	return true;
}

bool FGameTestRemoteServer::HandleCommandExecute(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	TSharedPtr<FJsonObject> RequestJson;
	FString ParseError;
	if (!ParseRequestJson(Request, RequestJson, ParseError))
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("invalid_json"), ParseError)));
		return true;
	}

	const FString SessionId = ReadStringFieldOrDefault(RequestJson, TEXT("session_id"));
	if (SessionId.IsEmpty())
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("missing_field"), TEXT("session_id is required."))));
		return true;
	}

	if (!SessionManager.HasSession(SessionId))
	{
		TSharedRef<FJsonObject> ErrorJson = MakeErrorJson(TEXT("session_not_found"), TEXT("session_id is not active."));
		ErrorJson->SetStringField(TEXT("session_id"), SessionId);
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::NotFound, ErrorJson));
		return true;
	}

	const FGameTestCommandResponse CommandResponse = FGameTestCommandService::ExecuteFromJsonObject(RequestJson);
	TSharedRef<FJsonObject> JsonBody = CommandResponse.ToJsonObject();
	JsonBody->SetStringField(TEXT("session_id"), SessionId);

	const FString StepName = CommandResponse.CommandName.IsEmpty() ? TEXT("unknown_command") : CommandResponse.CommandName;
	const int32 StepIndex = 0;
	EventRecorder.RecordCommandStepStarted(
		SessionId,
		CommandResponse.TraceId,
		CommandResponse.CommandName,
		StepIndex,
		StepName,
		CommandResponse.Details);

	if (CommandResponse.bAccepted)
	{
		const TSharedRef<FJsonObject> TargetStateBefore = RuntimeState.GetTargetState(SessionId);
		const int32 TargetHpBefore = ReadJsonInt(TargetStateBefore, TEXT("health"), 0);
		const bool bTargetAliveBefore = ReadJsonBool(TargetStateBefore, TEXT("alive"), true);
		const FString TargetActorId = ReadJsonString(TargetStateBefore, TEXT("actor_id"), TEXT("target_01"));

		RuntimeState.ApplyAcceptedCommand(SessionId, CommandResponse);
		const TSharedRef<FJsonObject> TargetStateAfter = RuntimeState.GetTargetState(SessionId);
		const int32 TargetHpAfter = ReadJsonInt(TargetStateAfter, TEXT("health"), TargetHpBefore);
		const bool bTargetAliveAfter = ReadJsonBool(TargetStateAfter, TEXT("alive"), bTargetAliveBefore);

		EventRecorder.RecordCommandAccepted(SessionId, CommandResponse.TraceId, CommandResponse.CommandName, CommandResponse.Details);
		EventRecorder.RecordCommandStepSucceeded(
			SessionId,
			CommandResponse.TraceId,
			CommandResponse.CommandName,
			StepIndex,
			StepName,
			CommandResponse.Details);

		if (CommandResponse.CommandName.Equals(TEXT("attack"), ESearchCase::IgnoreCase) && TargetHpAfter < TargetHpBefore)
		{
			TSharedPtr<FJsonObject> DamagePayload = MakeShared<FJsonObject>();
			DamagePayload->SetStringField(TEXT("source_actor_id"), ReadJsonString(RuntimeState.GetPlayerState(SessionId), TEXT("actor_id"), TEXT("player_01")));
			DamagePayload->SetStringField(TEXT("target_actor_id"), TargetActorId);
			DamagePayload->SetNumberField(TEXT("amount"), static_cast<double>(TargetHpBefore - TargetHpAfter));
			DamagePayload->SetNumberField(TEXT("target_hp_before"), static_cast<double>(TargetHpBefore));
			DamagePayload->SetNumberField(TEXT("target_hp_after"), static_cast<double>(TargetHpAfter));
			DamagePayload->SetStringField(TEXT("trace_id"), CommandResponse.TraceId);
			EventRecorder.RecordCustomEvent(SessionId, CommandResponse.TraceId, TEXT("damage_applied"), DamagePayload);

			if (bTargetAliveBefore && !bTargetAliveAfter)
			{
				TSharedPtr<FJsonObject> DiedPayload = MakeShared<FJsonObject>();
				DiedPayload->SetStringField(TEXT("actor_id"), TargetActorId);
				DiedPayload->SetStringField(TEXT("trace_id"), CommandResponse.TraceId);
				EventRecorder.RecordCustomEvent(SessionId, CommandResponse.TraceId, TEXT("actor_died"), DiedPayload);
			}
		}

		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
		return true;
	}

	TSharedPtr<FJsonObject> RejectedPayload = MakeShared<FJsonObject>();
	RejectedPayload->SetStringField(TEXT("error_code"), CommandResponse.ErrorCode);
	RejectedPayload->SetStringField(TEXT("error_message"), CommandResponse.ErrorMessage);
	if (CommandResponse.Details.IsValid())
	{
		RejectedPayload->SetObjectField(TEXT("details"), CommandResponse.Details);
	}

	EventRecorder.RecordCommandRejected(
		SessionId,
		CommandResponse.TraceId,
		CommandResponse.CommandName,
		CommandResponse.ErrorMessage,
		RejectedPayload);
	EventRecorder.RecordCommandStepFailed(
		SessionId,
		CommandResponse.TraceId,
		CommandResponse.CommandName,
		StepIndex,
		CommandResponse.ErrorCode,
		CommandResponse.ErrorMessage,
		StepName,
		CommandResponse.Details);

	OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, JsonBody));
	return true;
}

bool FGameTestRemoteServer::HandleScreenshotCapture(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	FString SessionId;
	if (!TryGetSessionIdFromQuery(Request, SessionId))
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("missing_query"), TEXT("session_id query parameter is required."))));
		return true;
	}

	if (!SessionManager.HasSession(SessionId))
	{
		TSharedRef<FJsonObject> ErrorJson = MakeErrorJson(TEXT("session_not_found"), TEXT("session_id is not active."));
		ErrorJson->SetStringField(TEXT("session_id"), SessionId);
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::NotFound, ErrorJson));
		return true;
	}

	const int32 RequestedHeight = FMath::Max(1, GetPositiveQueryIntOrDefault(Request, TEXT("height"), 360));
	bool bPreserveAspectRatio = true;
	(void)TryGetQueryBool(Request, TEXT("preserve_aspect_ratio"), bPreserveAspectRatio);
	const int32 RequestedJpegQuality = FMath::Clamp(GetPositiveQueryIntOrDefault(Request, TEXT("jpeg_quality"), 60), 1, 100);

	FViewportScreenshotCaptureResult CaptureResult;
	if (!TryCaptureViewportScreenshot(CaptureResult, 5.0))
	{
		const FString ErrorCode = CaptureResult.ErrorCode.IsEmpty() ? TEXT("capture_unavailable") : CaptureResult.ErrorCode;
		const FString ErrorMessage = CaptureResult.ErrorMessage.IsEmpty()
			? TEXT("Failed to capture the target viewport.")
			: CaptureResult.ErrorMessage;

		TSharedRef<FJsonObject> ErrorJson = MakeErrorJson(ErrorCode, ErrorMessage);
		ErrorJson->SetStringField(TEXT("captured_session_id"), SessionId);
		ErrorJson->SetNumberField(TEXT("jpeg_quality"), static_cast<double>(RequestedJpegQuality));
		if (CaptureResult.bHasViewportState)
		{
			ErrorJson->SetObjectField(TEXT("viewport_state"), BuildViewportStateJson(CaptureResult));
		}

		const EHttpServerResponseCodes ResponseCode =
			(ErrorCode == TEXT("viewport_minimized") || ErrorCode == TEXT("viewport_occluded"))
				? EHttpServerResponseCodes::Conflict
				: (ErrorCode == TEXT("capture_timeout") ? EHttpServerResponseCodes::GatewayTimeout : EHttpServerResponseCodes::ServiceUnavail);

		OnComplete(MakeJsonResponse(ResponseCode, ErrorJson));
		return true;
	}

	FString ImageBase64;
	int32 OutputWidth = 0;
	int32 OutputHeight = 0;
	FString EncodeErrorCode;
	FString EncodeErrorMessage;
	if (!EncodeScreenshotToBase64Jpeg(
			CaptureResult.SourcePixels,
			CaptureResult.ViewportWidth,
			CaptureResult.ViewportHeight,
			RequestedHeight,
			bPreserveAspectRatio,
			RequestedJpegQuality,
			ImageBase64,
			OutputWidth,
			OutputHeight,
			EncodeErrorCode,
			EncodeErrorMessage))
	{
		TSharedRef<FJsonObject> ErrorJson = MakeErrorJson(
			EncodeErrorCode.IsEmpty() ? TEXT("capture_unavailable") : EncodeErrorCode,
			EncodeErrorMessage.IsEmpty() ? TEXT("Failed to encode the captured viewport.") : EncodeErrorMessage);
		ErrorJson->SetStringField(TEXT("captured_session_id"), SessionId);
		ErrorJson->SetNumberField(TEXT("jpeg_quality"), static_cast<double>(RequestedJpegQuality));
		ErrorJson->SetObjectField(TEXT("viewport_state"), BuildViewportStateJson(CaptureResult));
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::ServiceUnavail, ErrorJson));
		return true;
	}

	TSharedRef<FJsonObject> JsonBody = MakeShared<FJsonObject>();
	JsonBody->SetBoolField(TEXT("accepted"), true);
	JsonBody->SetStringField(TEXT("captured_session_id"), SessionId);
	JsonBody->SetStringField(TEXT("image_format"), TEXT("jpeg"));
	JsonBody->SetStringField(TEXT("image_base64"), ImageBase64);
	JsonBody->SetNumberField(TEXT("width"), static_cast<double>(OutputWidth));
	JsonBody->SetNumberField(TEXT("height"), static_cast<double>(OutputHeight));
	JsonBody->SetNumberField(TEXT("jpeg_quality"), static_cast<double>(RequestedJpegQuality));
	JsonBody->SetObjectField(TEXT("viewport_state"), BuildViewportStateJson(CaptureResult));

	OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
	return true;
}

bool FGameTestRemoteServer::HandlePlayerState(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	FString SessionId;
	if (!TryGetSessionIdFromQuery(Request, SessionId))
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("missing_query"), TEXT("session_id query parameter is required."))));
		return true;
	}

	if (!SessionManager.HasSession(SessionId))
	{
		TSharedRef<FJsonObject> ErrorJson = MakeErrorJson(TEXT("session_not_found"), TEXT("session_id is not active."));
		ErrorJson->SetStringField(TEXT("session_id"), SessionId);
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::NotFound, ErrorJson));
		return true;
	}

	const TSharedRef<FJsonObject> JsonBody = RuntimeState.GetPlayerState(SessionId);
	OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
	return true;
}

bool FGameTestRemoteServer::HandleTargetState(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	FString SessionId;
	if (!TryGetSessionIdFromQuery(Request, SessionId))
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("missing_query"), TEXT("session_id query parameter is required."))));
		return true;
	}

	if (!SessionManager.HasSession(SessionId))
	{
		TSharedRef<FJsonObject> ErrorJson = MakeErrorJson(TEXT("session_not_found"), TEXT("session_id is not active."));
		ErrorJson->SetStringField(TEXT("session_id"), SessionId);
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::NotFound, ErrorJson));
		return true;
	}

	const TSharedRef<FJsonObject> JsonBody = RuntimeState.GetTargetState(SessionId);
	OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
	return true;
}

bool FGameTestRemoteServer::HandleSpatialState(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	FString SessionId;
	if (!TryGetSessionIdFromQuery(Request, SessionId))
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("missing_query"), TEXT("session_id query parameter is required."))));
		return true;
	}

	if (!SessionManager.HasSession(SessionId))
	{
		TSharedRef<FJsonObject> ErrorJson = MakeErrorJson(TEXT("session_not_found"), TEXT("session_id is not active."));
		ErrorJson->SetStringField(TEXT("session_id"), SessionId);
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::NotFound, ErrorJson));
		return true;
	}

	TSharedRef<FJsonObject> JsonBody = RuntimeState.GetSpatialState(SessionId);

	double ParsedDouble = 0.0;
	if (TryGetQueryDouble(Request, TEXT("distance_cm"), ParsedDouble))
	{
		JsonBody->SetNumberField(TEXT("distance_cm"), ParsedDouble);
	}

	if (TryGetQueryDouble(Request, TEXT("yaw_delta_degrees"), ParsedDouble))
	{
		JsonBody->SetNumberField(TEXT("yaw_delta_degrees"), ParsedDouble);
	}

	if (TryGetQueryDouble(Request, TEXT("recommended_left_stick_x"), ParsedDouble))
	{
		JsonBody->SetNumberField(TEXT("recommended_left_stick_x"), ParsedDouble);
	}

	if (TryGetQueryDouble(Request, TEXT("recommended_left_stick_y"), ParsedDouble))
	{
		JsonBody->SetNumberField(TEXT("recommended_left_stick_y"), ParsedDouble);
	}

	if (TryGetQueryDouble(Request, TEXT("navigation_path_length_cm"), ParsedDouble))
	{
		JsonBody->SetNumberField(TEXT("navigation_path_length_cm"), ParsedDouble);
	}

	bool ParsedBool = false;
	if (TryGetQueryBool(Request, TEXT("line_of_sight"), ParsedBool))
	{
		JsonBody->SetBoolField(TEXT("line_of_sight"), ParsedBool);
	}

	if (TryGetQueryBool(Request, TEXT("target_in_attack_range"), ParsedBool))
	{
		JsonBody->SetBoolField(TEXT("target_in_attack_range"), ParsedBool);
	}
	OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
	return true;
}

bool FGameTestRemoteServer::HandleEvents(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
	FString SessionId;
	if (!TryGetSessionIdFromQuery(Request, SessionId))
	{
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::BadRequest, MakeErrorJson(TEXT("missing_query"), TEXT("session_id query parameter is required."))));
		return true;
	}

	if (!SessionManager.HasSession(SessionId))
	{
		TSharedRef<FJsonObject> ErrorJson = MakeErrorJson(TEXT("session_not_found"), TEXT("session_id is not active."));
		ErrorJson->SetStringField(TEXT("session_id"), SessionId);
		OnComplete(MakeJsonResponse(EHttpServerResponseCodes::NotFound, ErrorJson));
		return true;
	}

	const FString TypeFilter = GetQueryOrDefault(Request, TEXT("type"));
	const int32 Limit = GetPositiveQueryIntOrDefault(Request, TEXT("limit"), 0);
	const int64 AfterSequence = GetNonNegativeQueryInt64OrDefault(Request, TEXT("after_sequence"), 0);

	TSharedRef<FJsonObject> JsonBody = EventRecorder.GetRecentEventsJson(SessionId, TypeFilter, Limit, AfterSequence);
	OnComplete(MakeJsonResponse(EHttpServerResponseCodes::Ok, JsonBody));
	return true;
}

void FGameTestRemoteServer::HandleRecordedEvent(const FGameTestEventRecord& Event)
{
	if (WebSocketServer.IsValid())
	{
		WebSocketServer->BroadcastEvent(Event);
	}
}

bool FGameTestRemoteServer::ParseRequestJson(const FHttpServerRequest& Request, TSharedPtr<FJsonObject>& OutJson, FString& OutError)
{
	OutJson = MakeShared<FJsonObject>();
	OutError.Empty();

	if (Request.Body.Num() == 0)
	{
		return true;
	}

	const UTF8CHAR* BodyData = reinterpret_cast<const UTF8CHAR*>(Request.Body.GetData());
	const FUTF8ToTCHAR Converter(BodyData, Request.Body.Num());
	const FString BodyString(Converter.Length(), Converter.Get());

	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(BodyString);
	if (!FJsonSerializer::Deserialize(Reader, OutJson) || !OutJson.IsValid())
	{
		OutError = TEXT("Failed to parse request body as JSON object.");
		return false;
	}

	return true;
}

TUniquePtr<FHttpServerResponse> FGameTestRemoteServer::MakeJsonResponse(EHttpServerResponseCodes ResponseCode, const TSharedRef<FJsonObject>& JsonBody)
{
	FString ResponseBody;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&ResponseBody);
	FJsonSerializer::Serialize(JsonBody, Writer);

	TUniquePtr<FHttpServerResponse> Response = FHttpServerResponse::Create(ResponseBody, TEXT("application/json; charset=utf-8"));
	Response->Code = ResponseCode;
	return Response;
}

TSharedRef<FJsonObject> FGameTestRemoteServer::MakeErrorJson(const FString& ErrorCode, const FString& Message)
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	Json->SetBoolField(TEXT("accepted"), false);
	Json->SetStringField(TEXT("error"), ErrorCode);
	Json->SetStringField(TEXT("error_code"), ErrorCode);
	Json->SetStringField(TEXT("message"), Message);
	Json->SetStringField(TEXT("error_message"), Message);
	Json->SetStringField(TEXT("timestamp"), FDateTime::UtcNow().ToIso8601());
	return Json;
}

FString FGameTestRemoteServer::ReadStringFieldOrDefault(const TSharedPtr<FJsonObject>& Json, const FString& FieldName, const FString& DefaultValue)
{
	if (!Json.IsValid())
	{
		return DefaultValue;
	}

	FString Value;
	if (Json->TryGetStringField(FieldName, Value))
	{
		return Value;
	}

	return DefaultValue;
}

bool FGameTestRemoteServer::TryGetSessionIdFromQuery(const FHttpServerRequest& Request, FString& OutSessionId) const
{
	if (const FString* SessionIdPtr = Request.QueryParams.Find(TEXT("session_id")))
	{
		OutSessionId = SessionIdPtr->TrimStartAndEnd();
		return !OutSessionId.IsEmpty();
	}

	OutSessionId.Reset();
	return false;
}

FString FGameTestRemoteServer::BuildWebSocketUrl() const
{
	if (WebSocketPort == 0)
	{
		return FString();
	}

	return FString::Printf(TEXT("ws://127.0.0.1:%u/events"), static_cast<uint32>(WebSocketPort));
}

bool FGameTestRemoteServer::StartWebSocketStream()
{
	if (WebSocketServer.IsValid())
	{
		return true;
	}

	const uint16 CandidatePort = (ListeningPort >= 65535) ? static_cast<uint16>(ListeningPort - 1) : static_cast<uint16>(ListeningPort + 1);
	WebSocketPort = CandidatePort;
	WebSocketServer = MakeUnique<FGameTestWebSocketServer>(WebSocketPort);
	if (!WebSocketServer->Start())
	{
		WebSocketServer.Reset();
		WebSocketPort = 0;
		return false;
	}

	return true;
}

void FGameTestRemoteServer::StopWebSocketStream()
{
	if (WebSocketServer.IsValid())
	{
		WebSocketServer->Shutdown();
		WebSocketServer.Reset();
	}
}
