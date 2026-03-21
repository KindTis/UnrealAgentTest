// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

struct FActorsInitializedParams;

class FUnrealAgentTestModule : public IModuleInterface
{
public:

	/** IModuleInterface implementation */
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

private:
	void HandleWorldInitializedActors(const FActorsInitializedParams& InParams);

	FDelegateHandle WorldInitializedActorsDelegateHandle;
};
