#include "GameTestInputExecutor.h"

#include "Async/Async.h"
#include "Containers/Ticker.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformProcess.h"
#include "InputCoreTypes.h"
#include "InputKeyEventArgs.h"

namespace
{
	FString NormalizeToken(const FString& Value)
	{
		FString Result = Value;
		Result.TrimStartAndEndInline();
		return Result.ToLower();
	}

	TSharedRef<FJsonObject> EnsureDetails(TSharedPtr<FJsonObject>& Details)
	{
		if (!Details.IsValid())
		{
			Details = MakeShared<FJsonObject>();
		}

		return Details.ToSharedRef();
	}

	void SetDetailsString(TSharedPtr<FJsonObject>& Details, const FString& Key, const FString& Value)
	{
		EnsureDetails(Details)->SetStringField(Key, Value);
	}

	void SetDetailsBool(TSharedPtr<FJsonObject>& Details, const FString& Key, bool Value)
	{
		EnsureDetails(Details)->SetBoolField(Key, Value);
	}

	void SetDetailsNumber(TSharedPtr<FJsonObject>& Details, const FString& Key, double Value)
	{
		EnsureDetails(Details)->SetNumberField(Key, Value);
	}

	bool TryReadStringField(const TSharedPtr<FJsonObject>& Json, const FString& FieldName, FString& OutValue)
	{
		if (!Json.IsValid())
		{
			return false;
		}

		if (!Json->TryGetStringField(FieldName, OutValue))
		{
			return false;
		}

		OutValue.TrimStartAndEndInline();
		return !OutValue.IsEmpty();
	}

	bool TryReadNumberField(const TSharedPtr<FJsonObject>& Json, const FString& FieldName, double& OutValue)
	{
		return Json.IsValid() && Json->TryGetNumberField(FieldName, OutValue);
	}

	APlayerController* ResolvePlayerController(TSharedPtr<FJsonObject>& Details, FString& OutErrorMessage)
	{
		if (GEngine == nullptr)
		{
			OutErrorMessage = TEXT("GEngine is not available.");
			return nullptr;
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

			SetDetailsString(Details, TEXT("resolved_world"), World->GetName());
			SetDetailsString(Details, TEXT("resolved_player_controller"), PlayerController->GetName());
			return PlayerController;
		}

		OutErrorMessage = TEXT("Could not resolve an active game world and player controller.");
		return nullptr;
	}

	bool SendSimulatedKey(APlayerController* PlayerController, const FKey& Key, EInputEvent Event, float AmountDepressed)
	{
		if (PlayerController == nullptr)
		{
			return false;
		}

		return PlayerController->InputKey(FInputKeyEventArgs::CreateSimulated(Key, Event, AmountDepressed));
	}

	FString JoinStrings(const TArray<FString>& Values, const TCHAR* Delimiter)
	{
		FString Joined;
		for (int32 Index = 0; Index < Values.Num(); ++Index)
		{
			if (Index > 0)
			{
				Joined += Delimiter;
			}
			Joined += Values[Index];
		}

		return Joined;
	}

	bool TryMapButtonIdToKeys(const FString& ButtonId, TArray<FKey>& OutKeys)
	{
		const FString Normalized = NormalizeToken(ButtonId);
		if (Normalized.IsEmpty())
		{
			return false;
		}

		if (Normalized == TEXT("attack"))
		{
			OutKeys = {EKeys::LeftMouseButton, EKeys::Gamepad_RightShoulder};
			return true;
		}
		if (Normalized == TEXT("jump"))
		{
			// Keep keyboard SpaceBar as primary and try face-bottom as a fallback key path.
			OutKeys = {EKeys::SpaceBar, EKeys::Gamepad_FaceButton_Bottom};
			return true;
		}
		if (Normalized == TEXT("face_bottom") || Normalized == TEXT("confirm") || Normalized == TEXT("interact"))
		{
			OutKeys = {EKeys::Gamepad_FaceButton_Bottom, EKeys::SpaceBar};
			return true;
		}
		if (Normalized == TEXT("face_top"))
		{
			OutKeys = {EKeys::Gamepad_FaceButton_Top};
			return true;
		}
		if (Normalized == TEXT("face_left"))
		{
			OutKeys = {EKeys::Gamepad_FaceButton_Left};
			return true;
		}
		if (Normalized == TEXT("face_right"))
		{
			OutKeys = {EKeys::Gamepad_FaceButton_Right};
			return true;
		}
		if (Normalized == TEXT("left_shoulder"))
		{
			OutKeys = {EKeys::Gamepad_LeftShoulder};
			return true;
		}
		if (Normalized == TEXT("right_shoulder"))
		{
			OutKeys = {EKeys::Gamepad_RightShoulder};
			return true;
		}
		if (Normalized == TEXT("dpad_up"))
		{
			OutKeys = {EKeys::Gamepad_DPad_Up};
			return true;
		}
		if (Normalized == TEXT("dpad_down"))
		{
			OutKeys = {EKeys::Gamepad_DPad_Down};
			return true;
		}
		if (Normalized == TEXT("dpad_left"))
		{
			OutKeys = {EKeys::Gamepad_DPad_Left};
			return true;
		}
		if (Normalized == TEXT("dpad_right"))
		{
			OutKeys = {EKeys::Gamepad_DPad_Right};
			return true;
		}
		if (Normalized == TEXT("start"))
		{
			OutKeys = {EKeys::Gamepad_Special_Right};
			return true;
		}
		if (Normalized == TEXT("back"))
		{
			OutKeys = {EKeys::Gamepad_Special_Left};
			return true;
		}

		return false;
	}

	bool TryResolveStickKeys(const FString& StickId, FKey& OutXKey, FKey& OutYKey, FString& OutResolvedStick)
	{
		const FString Normalized = NormalizeToken(StickId);
		if (Normalized == TEXT("left") || Normalized == TEXT("left_stick") || Normalized == TEXT("move"))
		{
			OutXKey = EKeys::Gamepad_LeftX;
			OutYKey = EKeys::Gamepad_LeftY;
			OutResolvedStick = TEXT("left_stick");
			return true;
		}

		if (Normalized == TEXT("right") || Normalized == TEXT("right_stick") || Normalized == TEXT("look"))
		{
			OutXKey = EKeys::Gamepad_RightX;
			OutYKey = EKeys::Gamepad_RightY;
			OutResolvedStick = TEXT("right_stick");
			return true;
		}

		return false;
	}

	bool ExecuteTapButton(APlayerController* PlayerController, const TSharedPtr<FJsonObject>& NormalizedArgs, TSharedPtr<FJsonObject>& Details, FString& OutErrorMessage)
	{
		FString ButtonId;
		if (!TryReadStringField(NormalizedArgs, TEXT("button_id"), ButtonId))
		{
			OutErrorMessage = TEXT("button_id is missing from normalized_args.");
			return false;
		}

		TArray<FKey> CandidateKeys;
		if (!TryMapButtonIdToKeys(ButtonId, CandidateKeys))
		{
			OutErrorMessage = FString::Printf(TEXT("Unsupported native button mapping for button_id '%s'."), *ButtonId);
			return false;
		}

		double DurationMs = 100.0;
		if (NormalizedArgs.IsValid())
		{
			double RequestedDurationMs = 0.0;
			if (TryReadNumberField(NormalizedArgs, TEXT("duration_ms"), RequestedDurationMs) && RequestedDurationMs > 0.0)
			{
				DurationMs = RequestedDurationMs;
			}
		}
		const float HoldSeconds = FMath::Clamp(static_cast<float>(DurationMs / 1000.0), 0.0f, 2.0f);
		const bool bIsJumpButton = NormalizeToken(ButtonId) == TEXT("jump");
		TArray<FString> HandledKeyNames;
		bool bAnyPressedHandled = false;
		bool bAnyReleasedHandled = false;
		bool bAnyReleaseScheduled = false;

		for (const FKey& Key : CandidateKeys)
		{
			const bool bPressedHandled = SendSimulatedKey(PlayerController, Key, IE_Pressed, 1.0f);
			bool bReleasedHandled = false;
			bool bReleaseScheduled = false;

			if (bPressedHandled)
			{
				TWeakObjectPtr<APlayerController> WeakController(PlayerController);
				FTSTicker::GetCoreTicker().AddTicker(
					FTickerDelegate::CreateLambda([WeakController, Key](float)
					{
						if (APlayerController* ValidController = WeakController.Get())
						{
							(void)SendSimulatedKey(ValidController, Key, IE_Released, 0.0f);
						}
						return false;
					}),
					FMath::Max(0.0f, HoldSeconds));

				bReleasedHandled = true;
				bReleaseScheduled = true;
			}

			if (bPressedHandled || bReleasedHandled)
			{
				HandledKeyNames.Add(Key.GetFName().ToString());
				bAnyPressedHandled = bAnyPressedHandled || bPressedHandled;
				bAnyReleasedHandled = bAnyReleasedHandled || bReleasedHandled;
				bAnyReleaseScheduled = bAnyReleaseScheduled || bReleaseScheduled;

				if (!bIsJumpButton)
				{
					SetDetailsString(Details, TEXT("input_key"), Key.GetFName().ToString());
					SetDetailsString(Details, TEXT("input_mode"), TEXT("tap"));
					SetDetailsNumber(Details, TEXT("tap_duration_ms"), DurationMs);
					SetDetailsBool(Details, TEXT("pressed_handled"), bPressedHandled);
					SetDetailsBool(Details, TEXT("released_handled"), bReleasedHandled);
					SetDetailsBool(Details, TEXT("release_scheduled"), bReleaseScheduled);
					SetDetailsNumber(Details, TEXT("release_delay_seconds"), HoldSeconds);
					return true;
				}
			}
		}

		if (bIsJumpButton && HandledKeyNames.Num() > 0)
		{
			SetDetailsString(Details, TEXT("input_key"), JoinStrings(HandledKeyNames, TEXT(",")));
			SetDetailsString(Details, TEXT("input_mode"), TEXT("tap_jump_fallback"));
			SetDetailsNumber(Details, TEXT("tap_duration_ms"), DurationMs);
			SetDetailsBool(Details, TEXT("pressed_handled"), bAnyPressedHandled);
			SetDetailsBool(Details, TEXT("released_handled"), bAnyReleasedHandled);
			SetDetailsBool(Details, TEXT("release_scheduled"), bAnyReleaseScheduled);
			SetDetailsNumber(Details, TEXT("release_delay_seconds"), HoldSeconds);
			SetDetailsBool(Details, TEXT("jump_fallback_used"), HandledKeyNames.Num() > 1);
			return true;
		}

		OutErrorMessage = FString::Printf(TEXT("PlayerController did not handle any mapped keys for button_id '%s'."), *ButtonId);
		return false;
	}

	bool ExecuteAttack(APlayerController* PlayerController, TSharedPtr<FJsonObject>& Details, FString& OutErrorMessage)
	{
		TArray<FKey> CandidateKeys = {EKeys::LeftMouseButton, EKeys::Gamepad_RightShoulder};
		for (const FKey& Key : CandidateKeys)
		{
			const bool bPressedHandled = SendSimulatedKey(PlayerController, Key, IE_Pressed, 1.0f);
			const bool bReleasedHandled = SendSimulatedKey(PlayerController, Key, IE_Released, 0.0f);
			if (bPressedHandled || bReleasedHandled)
			{
				SetDetailsString(Details, TEXT("input_key"), Key.GetFName().ToString());
				SetDetailsString(Details, TEXT("input_mode"), TEXT("attack"));
				return true;
			}
		}

		OutErrorMessage = TEXT("PlayerController did not handle any native attack input candidates.");
		return false;
	}

	bool ExecuteMoveStick(APlayerController* PlayerController, const TSharedPtr<FJsonObject>& NormalizedArgs, bool bReleaseOnly, TSharedPtr<FJsonObject>& Details, FString& OutErrorMessage)
	{
		FString StickId;
		if (!TryReadStringField(NormalizedArgs, TEXT("stick_id"), StickId))
		{
			OutErrorMessage = TEXT("stick_id is missing from normalized_args.");
			return false;
		}

		FKey XKey;
		FKey YKey;
		FString ResolvedStick;
		if (!TryResolveStickKeys(StickId, XKey, YKey, ResolvedStick))
		{
			OutErrorMessage = FString::Printf(TEXT("Unsupported native stick mapping for stick_id '%s'."), *StickId);
			return false;
		}

		double XValue = 0.0;
		double YValue = 0.0;
		if (!bReleaseOnly)
		{
			(void)TryReadNumberField(NormalizedArgs, TEXT("x"), XValue);
			(void)TryReadNumberField(NormalizedArgs, TEXT("y"), YValue);
		}

		const bool bXHandled = SendSimulatedKey(PlayerController, XKey, IE_Axis, static_cast<float>(XValue));
		const bool bYHandled = SendSimulatedKey(PlayerController, YKey, IE_Axis, static_cast<float>(YValue));

		SetDetailsString(Details, TEXT("resolved_stick"), ResolvedStick);
		SetDetailsString(Details, TEXT("input_x_key"), XKey.GetFName().ToString());
		SetDetailsString(Details, TEXT("input_y_key"), YKey.GetFName().ToString());
		SetDetailsNumber(Details, TEXT("applied_x"), XValue);
		SetDetailsNumber(Details, TEXT("applied_y"), YValue);
		SetDetailsBool(Details, TEXT("input_x_handled"), bXHandled);
		SetDetailsBool(Details, TEXT("input_y_handled"), bYHandled);
		SetDetailsString(Details, TEXT("input_mode"), bReleaseOnly ? TEXT("release_stick") : TEXT("move_stick"));

		// Some input stacks do not report axis consumption even when axis values are propagated.
		// Keep command successful and expose handled flags in details for observability.
		if (!bXHandled && !bYHandled)
		{
			SetDetailsString(Details, TEXT("input_warning"), TEXT("axis_input_not_reported_handled"));
		}

		return true;
	}

	bool ExecuteCameraYaw(APlayerController* PlayerController, const TSharedPtr<FJsonObject>& NormalizedArgs, TSharedPtr<FJsonObject>& Details, FString& OutErrorMessage)
	{
		if (PlayerController == nullptr)
		{
			OutErrorMessage = TEXT("PlayerController is not available for camera_yaw.");
			return false;
		}

		double Degrees = 0.0;
		const bool bHasDegrees = TryReadNumberField(NormalizedArgs, TEXT("degrees"), Degrees)
			|| TryReadNumberField(NormalizedArgs, TEXT("delta_degrees"), Degrees);
		if (!bHasDegrees)
		{
			OutErrorMessage = TEXT("degrees or delta_degrees is missing from normalized_args.");
			return false;
		}

		const FRotator BeforeRotation = PlayerController->GetControlRotation();
		const float DeltaYaw = static_cast<float>(Degrees);
		APawn* Pawn = PlayerController->GetPawn();
		if (Pawn != nullptr)
		{
			Pawn->AddControllerYawInput(DeltaYaw);
		}

		FRotator AfterRotation = PlayerController->GetControlRotation();
		AfterRotation.Yaw = FRotator::NormalizeAxis(AfterRotation.Yaw + DeltaYaw);
		PlayerController->SetControlRotation(AfterRotation);

		SetDetailsString(Details, TEXT("input_mode"), TEXT("camera_yaw"));
		SetDetailsNumber(Details, TEXT("applied_degrees"), Degrees);
		SetDetailsBool(Details, TEXT("used_pawn_add_controller_yaw_input"), Pawn != nullptr);
		SetDetailsNumber(Details, TEXT("before_yaw"), BeforeRotation.Yaw);
		SetDetailsNumber(Details, TEXT("after_yaw"), AfterRotation.Yaw);
		return true;
	}

	bool ExecuteRecipe(APlayerController* PlayerController, const TSharedPtr<FJsonObject>& NormalizedArgs, TSharedPtr<FJsonObject>& Details, FString& OutErrorMessage)
	{
		if (PlayerController == nullptr)
		{
			OutErrorMessage = TEXT("PlayerController is not available for execute_recipe.");
			return false;
		}

		FString RecipeId;
		(void)TryReadStringField(NormalizedArgs, TEXT("recipe_id"), RecipeId);
		SetDetailsString(Details, TEXT("recipe_id"), RecipeId);
		SetDetailsString(Details, TEXT("recipe_execution_mode"), TEXT("native_bridge_only"));
		SetDetailsBool(Details, TEXT("recipe_steps_executed"), false);
		return true;
	}
}

FGameTestInputExecutionResult FGameTestInputExecutor::ExecuteCommand(const FGameTestInputExecutionRequest& Request)
{
	FGameTestInputExecutionResult Result;
	Result.Details = MakeShared<FJsonObject>();
	SetDetailsString(Result.Details, TEXT("command_name"), Request.CommandName);
	SetDetailsString(Result.Details, TEXT("trace_id"), Request.TraceId);

	auto ExecuteOnGameThread = [&Result, &Request]()
	{
		FString ResolveError;
		APlayerController* PlayerController = ResolvePlayerController(Result.Details, ResolveError);
		if (PlayerController == nullptr)
		{
			Result.bSucceeded = false;
			Result.ErrorMessage = ResolveError;
			return;
		}

		const FString CommandName = NormalizeToken(Request.CommandName);
		bool bExecuted = false;
		FString ExecutionError;

		if (CommandName == TEXT("attack"))
		{
			bExecuted = ExecuteAttack(PlayerController, Result.Details, ExecutionError);
		}
		else if (CommandName == TEXT("tap_button"))
		{
			bExecuted = ExecuteTapButton(PlayerController, Request.NormalizedArgs, Result.Details, ExecutionError);
		}
		else if (CommandName == TEXT("move_stick"))
		{
			bExecuted = ExecuteMoveStick(PlayerController, Request.NormalizedArgs, false, Result.Details, ExecutionError);
		}
		else if (CommandName == TEXT("release_stick"))
		{
			bExecuted = ExecuteMoveStick(PlayerController, Request.NormalizedArgs, true, Result.Details, ExecutionError);
		}
		else if (CommandName == TEXT("execute_recipe"))
		{
			bExecuted = ExecuteRecipe(PlayerController, Request.NormalizedArgs, Result.Details, ExecutionError);
		}
		else if (CommandName == TEXT("camera_yaw"))
		{
			bExecuted = ExecuteCameraYaw(PlayerController, Request.NormalizedArgs, Result.Details, ExecutionError);
		}
		else
		{
			ExecutionError = FString::Printf(TEXT("Unsupported command for native input execution: %s"), *Request.CommandName);
		}

		Result.bSucceeded = bExecuted;
		if (!bExecuted)
		{
			Result.ErrorMessage = ExecutionError;
		}
	};

	if (IsInGameThread())
	{
		ExecuteOnGameThread();
		return Result;
	}

	FEvent* CompletionEvent = FPlatformProcess::GetSynchEventFromPool(false);
	if (CompletionEvent == nullptr)
	{
		Result.bSucceeded = false;
		Result.ErrorMessage = TEXT("Failed to allocate completion event for game thread execution.");
		return Result;
	}

	AsyncTask(ENamedThreads::GameThread, [&ExecuteOnGameThread, CompletionEvent]()
	{
		ExecuteOnGameThread();
		CompletionEvent->Trigger();
	});

	CompletionEvent->Wait();
	FPlatformProcess::ReturnSynchEventToPool(CompletionEvent);

	return Result;
}
