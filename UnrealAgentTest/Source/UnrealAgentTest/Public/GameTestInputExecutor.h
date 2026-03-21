#pragma once

#include "CoreMinimal.h"

class FJsonObject;

struct FGameTestInputExecutionRequest
{
	FString CommandName;
	FString TraceId;
	TSharedPtr<FJsonObject> NormalizedArgs;
};

struct FGameTestInputExecutionResult
{
	bool bSucceeded = false;
	FString ErrorMessage;
	TSharedPtr<FJsonObject> Details;
	FString ImplementationStatus = TEXT("native_input");
};

class FGameTestInputExecutor
{
public:
	static FGameTestInputExecutionResult ExecuteCommand(const FGameTestInputExecutionRequest& Request);
};
