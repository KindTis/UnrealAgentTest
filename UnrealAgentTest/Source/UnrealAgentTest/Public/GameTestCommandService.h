#pragma once

#include "CoreMinimal.h"

class FJsonObject;

struct FGameTestCommandRequest
{
	FString CommandName;
	FString TraceId;
	TSharedPtr<FJsonObject> Arguments;
};

struct FGameTestCommandResponse
{
	bool bAccepted = false;
	FString CommandName;
	FString TraceId;
	FString ErrorCode;
	FString ErrorMessage;
	FString ErrorStage;
	FString TimestampUtc;
	FString ImplementationStatus;
	TSharedPtr<FJsonObject> Details;

	TSharedRef<FJsonObject> ToJsonObject() const;
	FString ToJsonString() const;
};

class FGameTestCommandService
{
public:
	static FGameTestCommandResponse ExecuteFromJson(const FString& RequestBodyJson);
	static FGameTestCommandResponse ExecuteFromJsonObject(const TSharedPtr<FJsonObject>& RequestJson);

private:
	static FGameTestCommandResponse ParseAndValidateRequest(const TSharedPtr<FJsonObject>& RequestJson);
	static bool TryBuildRequest(const TSharedPtr<FJsonObject>& RequestJson, FGameTestCommandRequest& OutRequest, FString& OutErrorStage, FString& OutErrorCode, FString& OutErrorMessage);
	static bool TryBuildCommandArguments(const TSharedPtr<FJsonObject>& RequestJson, TSharedPtr<FJsonObject>& OutArguments);
	static bool TryBuildAcceptedResponse(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse);

	static bool ValidateAttack(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse);
	static bool ValidateTapButton(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse);
	static bool ValidateMoveStick(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse);
	static bool ValidateReleaseStick(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse);
	static bool ValidateCameraYaw(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse);
	static bool ValidateExecuteRecipe(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse);

	static FString BuildTraceId();
	static FString BuildTimestampUtc();
	static FString NormalizeCommandName(const FString& CommandName);
	static FGameTestCommandResponse MakeRejected(const FString& CommandName, const FString& TraceId, const FString& ErrorStage, const FString& ErrorCode, const FString& ErrorMessage, const TSharedPtr<FJsonObject>& Details = nullptr);
	static void SetResponseDetailsString(TSharedPtr<FJsonObject>& Details, const FString& Key, const FString& Value);
	static void SetResponseDetailsNumber(TSharedPtr<FJsonObject>& Details, const FString& Key, double Value);
	static TSharedPtr<FJsonObject> MakeDetailsObject();
};
