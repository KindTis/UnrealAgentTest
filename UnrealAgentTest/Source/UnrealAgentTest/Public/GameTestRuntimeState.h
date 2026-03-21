#pragma once

#include "CoreMinimal.h"
#include "GameTestCommandService.h"
#include "GameTestQueryService.h"

class FJsonObject;

class FGameTestRuntimeState
{
public:
	explicit FGameTestRuntimeState(int32 InDefaultAttackDamage = 10);

	void EnsureSession(const FString& SessionId);
	bool RemoveSession(const FString& SessionId);

	TSharedRef<FJsonObject> GetPlayerState(const FString& SessionId) const;
	TSharedRef<FJsonObject> GetTargetState(const FString& SessionId) const;
	TSharedRef<FJsonObject> GetSpatialState(const FString& SessionId) const;

	bool ApplyAcceptedCommand(const FString& SessionId, const FGameTestCommandResponse& CommandResponse);
	bool ApplyAcceptedCommand(const FString& SessionId, const TSharedPtr<FJsonObject>& CommandResponseJson);
	bool ApplyAcceptedCommand(const FString& SessionId, const FString& CommandResponseJson);

private:
	struct FSessionRuntimeState
	{
		FString SessionId;
		FGameTestActorStateInput PlayerState;
		FGameTestActorStateInput TargetState;
		FGameTestSpatialStateInput SpatialState;
		TOptional<FGameTestVector3> ExplicitLeftStick;
		FString LastCommandName;
		FString LastTraceId;
		FDateTime LastUpdatedUtc;
	};

private:
	FSessionRuntimeState& GetOrCreateSessionState(const FString& SessionId) const;
	const FSessionRuntimeState* FindSessionState(const FString& SessionId) const;

	static FGameTestActorStateInput MakeDefaultPlayerState();
	static FGameTestActorStateInput MakeDefaultTargetState(const FString& TargetActorId);
	static FGameTestVector3 MakeVector(double X, double Y, double Z);
	static TSharedPtr<FJsonObject> FindObjectField(const TSharedPtr<FJsonObject>& Object, const FString& FieldName);
	static FString ReadStringField(const TSharedPtr<FJsonObject>& Object, const FString& FieldName, const FString& DefaultValue = FString());
	static double ReadDoubleField(const TSharedPtr<FJsonObject>& Object, const FString& FieldName, double DefaultValue = 0.0);
	static bool ReadBoolField(const TSharedPtr<FJsonObject>& Object, const FString& FieldName, bool DefaultValue = false);
	static FString ReadCommandName(const FGameTestCommandResponse& CommandResponse);
	static TSharedPtr<FJsonObject> ReadDetailsObject(const TSharedPtr<FJsonObject>& CommandResponseJson);
	static TSharedPtr<FJsonObject> ReadNormalizedArgsObject(const TSharedPtr<FJsonObject>& DetailsObject);
	static double ClampStickValue(double Value);
	static double ComputeDistanceCm(const FGameTestVector3& A, const FGameTestVector3& B);
	static double NormalizeDeltaDegrees(double Value);
	static FGameTestVector3 ComputeDirectionVector(const FGameTestVector3& From, const FGameTestVector3& To);
	static FGameTestVector3 ComputeForwardVector(const FGameTestRotator& Rotation);
	static FGameTestVector3 ComputeRightVector(const FGameTestRotator& Rotation);

	void InitializeSessionState(FSessionRuntimeState& SessionState, const FString& SessionId) const;
	void SyncSpatialState(FSessionRuntimeState& SessionState) const;
	void ApplyAcceptedCommand_Internal(FSessionRuntimeState& SessionState, const FGameTestCommandResponse& CommandResponse);
	void ApplyAttack(FSessionRuntimeState& SessionState, const TSharedPtr<FJsonObject>& NormalizedArgs);
	void ApplyMoveStick(FSessionRuntimeState& SessionState, const TSharedPtr<FJsonObject>& NormalizedArgs);
	void ApplyReleaseStick(FSessionRuntimeState& SessionState);
	void ApplyRecipe(FSessionRuntimeState& SessionState, const TSharedPtr<FJsonObject>& NormalizedArgs);
	void SetExplicitLeftStick(FSessionRuntimeState& SessionState, double X, double Y);
	void BuildStateMetadata(TSharedRef<FJsonObject>& JsonObject, const FSessionRuntimeState& SessionState) const;

private:
	mutable FCriticalSection StateLock;
	mutable TMap<FString, FSessionRuntimeState> SessionStates;
	int32 DefaultAttackDamage;
};
