// Copyright Epic Games, Inc. All Rights Reserved.

#include "UnrealAgentTest.h"
#include "GameTestRemoteServer.h"
#include "Engine/World.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

#define LOCTEXT_NAMESPACE "FUnrealAgentTestModule"

DEFINE_LOG_CATEGORY_STATIC(LogUnrealAgentTest, Log, All);

void FUnrealAgentTestModule::StartupModule()
{
	// This code will execute after your module is loaded into memory; the exact timing is specified in the .uplugin file per-module
	WorldInitializedActorsDelegateHandle = FWorldDelegates::OnWorldInitializedActors.AddRaw(this, &FUnrealAgentTestModule::HandleWorldInitializedActors);

	UE_LOG(LogUnrealAgentTest, Log, TEXT("UnrealAgentTest plugin module initialized."));
}

void FUnrealAgentTestModule::ShutdownModule()
{
	// This function may be called during shutdown to clean up your module.  For modules that support dynamic reloading,
	// we call this function before unloading the module.
	if (RemoteServer.IsValid())
	{
		RemoteServer->Stop();
		RemoteServer.Reset();
	}

	if (WorldInitializedActorsDelegateHandle.IsValid())
	{
		FWorldDelegates::OnWorldInitializedActors.Remove(WorldInitializedActorsDelegateHandle);
		WorldInitializedActorsDelegateHandle.Reset();
	}

	UE_LOG(LogUnrealAgentTest, Log, TEXT("UnrealAgentTest plugin module shutdown."));
}

void FUnrealAgentTestModule::HandleWorldInitializedActors(const FActorsInitializedParams& InParams)
{
	UWorld* InWorld = InParams.World;

	if (InWorld == nullptr || !InWorld->IsGameWorld())
	{
		return;
	}

	UE_LOG(LogUnrealAgentTest, Log, TEXT("Gameplay started in world: %s"), *InWorld->GetName());

	if (!ShouldEnableRemoteServer())
	{
		return;
	}

	if (!RemoteServer.IsValid())
	{
		RemoteServer = MakeUnique<FGameTestRemoteServer>();
	}

	if (RemoteServer->IsRunning())
	{
		return;
	}

	const uint16 Port = ResolveRemoteServerPort();
	if (!RemoteServer->Start(Port))
	{
		UE_LOG(LogUnrealAgentTest, Error, TEXT("Failed to start GameTest remote API server on port %d."), Port);
		return;
	}

	UE_LOG(LogUnrealAgentTest, Log, TEXT("GameTest remote API server enabled on localhost:%d."), Port);
}

bool FUnrealAgentTestModule::ShouldEnableRemoteServer() const
{
	const TCHAR* CommandLine = FCommandLine::Get();
	return FParse::Param(CommandLine, TEXT("TestMode")) || FParse::Param(CommandLine, TEXT("GameTestRemoteApi"));
}

uint16 FUnrealAgentTestModule::ResolveRemoteServerPort() const
{
	int32 RequestedPort = 0;
	if (FParse::Value(FCommandLine::Get(), TEXT("Port="), RequestedPort))
	{
		if (RequestedPort >= 1 && RequestedPort <= 65535)
		{
			return static_cast<uint16>(RequestedPort);
		}
	}

	return 31001;
}

#undef LOCTEXT_NAMESPACE
	
IMPLEMENT_MODULE(FUnrealAgentTestModule, UnrealAgentTest)
