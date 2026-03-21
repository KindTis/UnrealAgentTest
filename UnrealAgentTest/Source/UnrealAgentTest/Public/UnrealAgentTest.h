// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

class FGameTestRemoteServer;
struct FActorsInitializedParams;

class FUnrealAgentTestModule : public IModuleInterface
{
public:

	/** IModuleInterface implementation */
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

private:
	bool ShouldEnableRemoteServer() const;
	uint16 ResolveRemoteServerPort() const;
	void HandleWorldInitializedActors(const FActorsInitializedParams& InParams);

	FDelegateHandle WorldInitializedActorsDelegateHandle;
	TUniquePtr<FGameTestRemoteServer> RemoteServer;
};
