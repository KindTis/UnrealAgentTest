// Copyright Epic Games, Inc. All Rights Reserved.

#include "UnrealAgentTest.h"
#include "Engine/World.h"

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
}

#undef LOCTEXT_NAMESPACE
	
IMPLEMENT_MODULE(FUnrealAgentTestModule, UnrealAgentTest)
