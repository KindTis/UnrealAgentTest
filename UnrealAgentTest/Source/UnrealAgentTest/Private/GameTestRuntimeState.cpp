#include "GameTestRuntimeState.h"

#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	FString TrimmedCopy(const FString& Value)
	{
		FString Result = Value;
		Result.TrimStartAndEndInline();
		return Result;
	}

	FString NormalizeSessionId(const FString& SessionId)
	{
		const FString Trimmed = TrimmedCopy(SessionId);
		return Trimmed.IsEmpty() ? FString(TEXT("default")) : Trimmed;
	}

	bool TryGetStringFieldAny(const TSharedPtr<FJsonObject>& Object, const TArray<FString>& FieldNames, FString& OutValue)
	{
		if (!Object.IsValid())
		{
			return false;
		}

		for (const FString& FieldName : FieldNames)
		{
			if (Object->TryGetStringField(FieldName, OutValue))
			{
				return true;
			}
		}

		return false;
	}

	bool TryGetNumberFieldAny(const TSharedPtr<FJsonObject>& Object, const TArray<FString>& FieldNames, double& OutValue)
	{
		if (!Object.IsValid())
		{
			return false;
		}

		for (const FString& FieldName : FieldNames)
		{
			if (Object->TryGetNumberField(FieldName, OutValue))
			{
				return true;
			}
		}

		return false;
	}

	bool TryGetBoolFieldAny(const TSharedPtr<FJsonObject>& Object, const TArray<FString>& FieldNames, bool& OutValue)
	{
		if (!Object.IsValid())
		{
			return false;
		}

		for (const FString& FieldName : FieldNames)
		{
			if (Object->TryGetBoolField(FieldName, OutValue))
			{
				return true;
			}
		}

		return false;
	}

	FGameTestActorStateInput MakeDefaultPlayerState()
	{
		FGameTestActorStateInput State;
		State.ActorId = TEXT("player_01");
		State.bAlive = true;
		State.Health = 100;
		State.MaxHealth = 100;
		State.Location = { 0.0, 0.0, 0.0 };
		State.Rotation = { 0.0, 0.0, 0.0 };
		State.Status = TEXT("idle");
		State.CurrentTargetId = TEXT("target_01");
		State.EquippedWeaponId = TEXT("weapon_default");
		State.CurrentAction = TEXT("idle");
		State.TeamId = TEXT("player");
		return State;
	}

	FGameTestActorStateInput MakeDefaultTargetState(const FString& TargetActorId)
	{
		FGameTestActorStateInput State;
		State.ActorId = TargetActorId.IsEmpty() ? TEXT("target_01") : TargetActorId;
		State.bAlive = true;
		State.Health = 100;
		State.MaxHealth = 100;
		State.Location = { 300.0, 0.0, 0.0 };
		State.Rotation = { 0.0, 180.0, 0.0 };
		State.Status = TEXT("hostile");
		State.CurrentTargetId = TEXT("");
		State.EquippedWeaponId = TEXT("");
		State.CurrentAction = TEXT("idle");
		State.TeamId = TEXT("hostile");
		return State;
	}

	FGameTestVector3 MakeVector(double X, double Y, double Z)
	{
		FGameTestVector3 Vector;
		Vector.X = X;
		Vector.Y = Y;
		Vector.Z = Z;
		return Vector;
	}

	double Dot2D(const FGameTestVector3& A, const FGameTestVector3& B)
	{
		return (A.X * B.X) + (A.Y * B.Y);
	}

	FString ReadCommandNameFromResponse(const FGameTestCommandResponse& CommandResponse)
	{
		return TrimmedCopy(CommandResponse.CommandName).ToLower();
	}

	TSharedPtr<FJsonObject> ReadDetailsObjectFromResponse(const TSharedPtr<FJsonObject>& CommandResponseJson)
	{
		TSharedPtr<FJsonObject> DetailsObject;
		if (CommandResponseJson.IsValid())
		{
			const TSharedPtr<FJsonValue>* FoundValue = CommandResponseJson->Values.Find(TEXT("details"));
			if (FoundValue && FoundValue->IsValid() && (*FoundValue)->Type == EJson::Object)
			{
				DetailsObject = (*FoundValue)->AsObject();
			}
		}

		if (!DetailsObject.IsValid())
		{
			if (CommandResponseJson.IsValid())
			{
				const TSharedPtr<FJsonValue>* FoundValue = CommandResponseJson->Values.Find(TEXT("Details"));
				if (FoundValue && FoundValue->IsValid() && (*FoundValue)->Type == EJson::Object)
				{
					DetailsObject = (*FoundValue)->AsObject();
				}
			}
		}

		return DetailsObject;
	}

}

FGameTestRuntimeState::FGameTestRuntimeState(int32 InDefaultAttackDamage)
	: DefaultAttackDamage(FMath::Max(1, InDefaultAttackDamage))
{
}

void FGameTestRuntimeState::EnsureSession(const FString& SessionId)
{
	const FString NormalizedSessionId = NormalizeSessionId(SessionId);
	FScopeLock Lock(&StateLock);
	FSessionRuntimeState& SessionState = GetOrCreateSessionState(NormalizedSessionId);
	InitializeSessionState(SessionState, NormalizedSessionId);
}

bool FGameTestRuntimeState::RemoveSession(const FString& SessionId)
{
	const FString NormalizedSessionId = NormalizeSessionId(SessionId);
	FScopeLock Lock(&StateLock);
	return SessionStates.Remove(NormalizedSessionId) > 0;
}

TSharedRef<FJsonObject> FGameTestRuntimeState::GetPlayerState(const FString& SessionId) const
{
	const FString NormalizedSessionId = NormalizeSessionId(SessionId);
	FSessionRuntimeState SessionSnapshot;
	{
		FScopeLock Lock(&StateLock);
		SessionSnapshot = GetOrCreateSessionState(NormalizedSessionId);
	}

	TSharedRef<FJsonObject> Json = FGameTestQueryService::BuildPlayerStateJson(SessionSnapshot.PlayerState);
	BuildStateMetadata(Json, SessionSnapshot);
	return Json;
}

TSharedRef<FJsonObject> FGameTestRuntimeState::GetTargetState(const FString& SessionId) const
{
	const FString NormalizedSessionId = NormalizeSessionId(SessionId);
	FSessionRuntimeState SessionSnapshot;
	{
		FScopeLock Lock(&StateLock);
		SessionSnapshot = GetOrCreateSessionState(NormalizedSessionId);
	}

	TSharedRef<FJsonObject> Json = FGameTestQueryService::BuildTargetStateJson(SessionSnapshot.TargetState);
	BuildStateMetadata(Json, SessionSnapshot);
	return Json;
}

TSharedRef<FJsonObject> FGameTestRuntimeState::GetSpatialState(const FString& SessionId) const
{
	const FString NormalizedSessionId = NormalizeSessionId(SessionId);
	FSessionRuntimeState SessionSnapshot;
	{
		FScopeLock Lock(&StateLock);
		SessionSnapshot = GetOrCreateSessionState(NormalizedSessionId);
	}

	TSharedRef<FJsonObject> Json = FGameTestQueryService::BuildSpatialStateJson(SessionSnapshot.SpatialState);
	BuildStateMetadata(Json, SessionSnapshot);
	return Json;
}

bool FGameTestRuntimeState::ApplyAcceptedCommand(const FString& SessionId, const FGameTestCommandResponse& CommandResponse)
{
	const FString NormalizedSessionId = NormalizeSessionId(SessionId);
	FScopeLock Lock(&StateLock);
	FSessionRuntimeState& SessionState = GetOrCreateSessionState(NormalizedSessionId);

	if (!CommandResponse.bAccepted)
	{
		SessionState.LastCommandName = ReadCommandNameFromResponse(CommandResponse);
		SessionState.LastTraceId = CommandResponse.TraceId;
		SessionState.LastUpdatedUtc = FDateTime::UtcNow();
		return false;
	}

	ApplyAcceptedCommand_Internal(SessionState, CommandResponse);
	return true;
}

bool FGameTestRuntimeState::ApplyAcceptedCommand(const FString& SessionId, const TSharedPtr<FJsonObject>& CommandResponseJson)
{
	if (!CommandResponseJson.IsValid())
	{
		return false;
	}

	FGameTestCommandResponse Response;
	bool bAccepted = false;
	(void)TryGetBoolFieldAny(CommandResponseJson, { TEXT("accepted"), TEXT("bAccepted") }, bAccepted);
	Response.bAccepted = bAccepted;
	(void)TryGetStringFieldAny(CommandResponseJson, { TEXT("command"), TEXT("command_name"), TEXT("CommandName") }, Response.CommandName);
	(void)TryGetStringFieldAny(CommandResponseJson, { TEXT("trace_id"), TEXT("TraceId") }, Response.TraceId);
	(void)TryGetStringFieldAny(CommandResponseJson, { TEXT("error_code"), TEXT("ErrorCode") }, Response.ErrorCode);
	(void)TryGetStringFieldAny(CommandResponseJson, { TEXT("error_message"), TEXT("ErrorMessage") }, Response.ErrorMessage);
	(void)TryGetStringFieldAny(CommandResponseJson, { TEXT("error_stage"), TEXT("ErrorStage") }, Response.ErrorStage);
	(void)TryGetStringFieldAny(CommandResponseJson, { TEXT("timestamp_utc"), TEXT("TimestampUtc") }, Response.TimestampUtc);
	(void)TryGetStringFieldAny(CommandResponseJson, { TEXT("implementation_status"), TEXT("ImplementationStatus") }, Response.ImplementationStatus);
	Response.Details = ReadDetailsObjectFromResponse(CommandResponseJson);

	return ApplyAcceptedCommand(SessionId, Response);
}

bool FGameTestRuntimeState::ApplyAcceptedCommand(const FString& SessionId, const FString& CommandResponseJson)
{
	if (CommandResponseJson.TrimStartAndEnd().IsEmpty())
	{
		return false;
	}

	TSharedPtr<FJsonObject> JsonObject;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(CommandResponseJson);
	if (!FJsonSerializer::Deserialize(Reader, JsonObject) || !JsonObject.IsValid())
	{
		return false;
	}

	return ApplyAcceptedCommand(SessionId, JsonObject);
}

FGameTestRuntimeState::FSessionRuntimeState& FGameTestRuntimeState::GetOrCreateSessionState(const FString& SessionId) const
{
	FSessionRuntimeState& SessionState = SessionStates.FindOrAdd(SessionId);
	if (SessionState.SessionId.IsEmpty())
	{
		InitializeSessionState(SessionState, SessionId);
	}

	return SessionState;
}

const FGameTestRuntimeState::FSessionRuntimeState* FGameTestRuntimeState::FindSessionState(const FString& SessionId) const
{
	return SessionStates.Find(SessionId);
}

FGameTestActorStateInput FGameTestRuntimeState::MakeDefaultPlayerState()
{
	return ::MakeDefaultPlayerState();
}

FGameTestActorStateInput FGameTestRuntimeState::MakeDefaultTargetState(const FString& TargetActorId)
{
	return ::MakeDefaultTargetState(TargetActorId);
}

FGameTestVector3 FGameTestRuntimeState::MakeVector(double X, double Y, double Z)
{
	return ::MakeVector(X, Y, Z);
}

TSharedPtr<FJsonObject> FGameTestRuntimeState::FindObjectField(const TSharedPtr<FJsonObject>& Object, const FString& FieldName)
{
	if (!Object.IsValid())
	{
		return nullptr;
	}

	const TSharedPtr<FJsonValue>* FoundValue = Object->Values.Find(FieldName);
	if (!FoundValue || !FoundValue->IsValid() || (*FoundValue)->Type != EJson::Object)
	{
		return nullptr;
	}

	return (*FoundValue)->AsObject();
}

FString FGameTestRuntimeState::ReadStringField(const TSharedPtr<FJsonObject>& Object, const FString& FieldName, const FString& DefaultValue)
{
	FString Value;
	if (Object.IsValid() && Object->TryGetStringField(FieldName, Value))
	{
		return Value;
	}

	return DefaultValue;
}

double FGameTestRuntimeState::ReadDoubleField(const TSharedPtr<FJsonObject>& Object, const FString& FieldName, double DefaultValue)
{
	double Value = DefaultValue;
	if (Object.IsValid() && Object->TryGetNumberField(FieldName, Value))
	{
		return Value;
	}

	return DefaultValue;
}

bool FGameTestRuntimeState::ReadBoolField(const TSharedPtr<FJsonObject>& Object, const FString& FieldName, bool DefaultValue)
{
	bool Value = DefaultValue;
	if (Object.IsValid() && Object->TryGetBoolField(FieldName, Value))
	{
		return Value;
	}

	return DefaultValue;
}

FString FGameTestRuntimeState::ReadCommandName(const FGameTestCommandResponse& CommandResponse)
{
	return ::ReadCommandNameFromResponse(CommandResponse);
}

TSharedPtr<FJsonObject> FGameTestRuntimeState::ReadDetailsObject(const TSharedPtr<FJsonObject>& CommandResponseJson)
{
	return ::ReadDetailsObjectFromResponse(CommandResponseJson);
}

TSharedPtr<FJsonObject> FGameTestRuntimeState::ReadNormalizedArgsObject(const TSharedPtr<FJsonObject>& DetailsObject)
{
	TSharedPtr<FJsonObject> NormalizedArgs = FindObjectField(DetailsObject, TEXT("normalized_args"));
	if (!NormalizedArgs.IsValid())
	{
		NormalizedArgs = FindObjectField(DetailsObject, TEXT("normalizedArgs"));
	}

	return NormalizedArgs;
}

double FGameTestRuntimeState::ClampStickValue(double Value)
{
	return FMath::Clamp(Value, -1.0, 1.0);
}

double FGameTestRuntimeState::ComputeDistanceCm(const FGameTestVector3& A, const FGameTestVector3& B)
{
	const double DeltaX = B.X - A.X;
	const double DeltaY = B.Y - A.Y;
	const double DeltaZ = B.Z - A.Z;
	return FMath::Sqrt((DeltaX * DeltaX) + (DeltaY * DeltaY) + (DeltaZ * DeltaZ));
}

double FGameTestRuntimeState::NormalizeDeltaDegrees(double Value)
{
	return FMath::UnwindDegrees(Value);
}

FGameTestVector3 FGameTestRuntimeState::ComputeDirectionVector(const FGameTestVector3& From, const FGameTestVector3& To)
{
	const double Distance = ComputeDistanceCm(From, To);
	if (Distance <= KINDA_SMALL_NUMBER)
	{
		return MakeVector(0.0, 0.0, 0.0);
	}

	return MakeVector((To.X - From.X) / Distance, (To.Y - From.Y) / Distance, (To.Z - From.Z) / Distance);
}

FGameTestVector3 FGameTestRuntimeState::ComputeForwardVector(const FGameTestRotator& Rotation)
{
	const double YawRadians = FMath::DegreesToRadians(Rotation.Yaw);
	return MakeVector(FMath::Cos(YawRadians), FMath::Sin(YawRadians), 0.0);
}

FGameTestVector3 FGameTestRuntimeState::ComputeRightVector(const FGameTestRotator& Rotation)
{
	const double YawRadians = FMath::DegreesToRadians(Rotation.Yaw);
	return MakeVector(-FMath::Sin(YawRadians), FMath::Cos(YawRadians), 0.0);
}

void FGameTestRuntimeState::InitializeSessionState(FSessionRuntimeState& SessionState, const FString& SessionId) const
{
	if (!SessionState.SessionId.IsEmpty())
	{
		return;
	}

	SessionState.SessionId = SessionId;
	SessionState.PlayerState = MakeDefaultPlayerState();
	SessionState.TargetState = MakeDefaultTargetState(SessionState.PlayerState.CurrentTargetId);
	SessionState.PlayerState.CurrentTargetId = SessionState.TargetState.ActorId;
	SessionState.ExplicitLeftStick.Reset();
	SessionState.LastCommandName = TEXT("session_start");
	SessionState.LastTraceId = FGameTestQueryService::CreateTraceId();
	SessionState.LastUpdatedUtc = FDateTime::UtcNow();

	SyncSpatialState(SessionState);
}

void FGameTestRuntimeState::SyncSpatialState(FSessionRuntimeState& SessionState) const
{
	const FGameTestVector3 PlayerLocation = SessionState.PlayerState.Location;
	const FGameTestVector3 TargetLocation = SessionState.TargetState.Location;
	const FGameTestVector3 DirectionToTarget = ComputeDirectionVector(PlayerLocation, TargetLocation);
	const FGameTestVector3 PlayerForward = ComputeForwardVector(SessionState.PlayerState.Rotation);
	const FGameTestVector3 TargetForward = ComputeForwardVector(SessionState.TargetState.Rotation);
	const FGameTestVector3 PlayerRight = ComputeRightVector(SessionState.PlayerState.Rotation);
	const double DistanceCm = ComputeDistanceCm(PlayerLocation, TargetLocation);
	const double YawDeltaDegrees = NormalizeDeltaDegrees(SessionState.TargetState.Rotation.Yaw - SessionState.PlayerState.Rotation.Yaw);
	const bool bWithinAttackRange = DistanceCm <= 150.0;

	double RecommendedLeftStickX = ClampStickValue(Dot2D(DirectionToTarget, PlayerRight));
	double RecommendedLeftStickY = ClampStickValue(Dot2D(DirectionToTarget, PlayerForward));
	if (SessionState.ExplicitLeftStick.IsSet())
	{
		RecommendedLeftStickX = ClampStickValue(SessionState.ExplicitLeftStick->X);
		RecommendedLeftStickY = ClampStickValue(SessionState.ExplicitLeftStick->Y);
	}

	SessionState.SpatialState.SessionId = SessionState.SessionId;
	SessionState.SpatialState.TraceId = SessionState.LastTraceId;
	SessionState.SpatialState.PlayerActorId = SessionState.PlayerState.ActorId;
	SessionState.SpatialState.TargetActorId = SessionState.TargetState.ActorId;
	SessionState.SpatialState.PlayerLocation = PlayerLocation;
	SessionState.SpatialState.TargetLocation = TargetLocation;
	SessionState.SpatialState.DirectionToTarget = DirectionToTarget;
	SessionState.SpatialState.PlayerForwardVector = PlayerForward;
	SessionState.SpatialState.TargetForwardVector = TargetForward;
	SessionState.SpatialState.DistanceCm = DistanceCm;
	SessionState.SpatialState.YawDeltaDegrees = YawDeltaDegrees;
	SessionState.SpatialState.RecommendedLeftStickX = RecommendedLeftStickX;
	SessionState.SpatialState.RecommendedLeftStickY = RecommendedLeftStickY;
	SessionState.SpatialState.NavigationPathLengthCm = DistanceCm;
	SessionState.SpatialState.bLineOfSight = true;
	SessionState.SpatialState.bTargetInAttackRange = bWithinAttackRange;
}

void FGameTestRuntimeState::ApplyAcceptedCommand_Internal(FSessionRuntimeState& SessionState, const FGameTestCommandResponse& CommandResponse)
{
	SessionState.LastCommandName = ReadCommandName(CommandResponse);
	SessionState.LastTraceId = CommandResponse.TraceId;
	SessionState.LastUpdatedUtc = FDateTime::UtcNow();

	const TSharedPtr<FJsonObject> DetailsObject = CommandResponse.Details;
	const TSharedPtr<FJsonObject> NormalizedArgs = ReadNormalizedArgsObject(DetailsObject);

	if (SessionState.LastCommandName == TEXT("attack"))
	{
		ApplyAttack(SessionState, NormalizedArgs);
	}
	else if (SessionState.LastCommandName == TEXT("move_stick"))
	{
		ApplyMoveStick(SessionState, NormalizedArgs);
	}
	else if (SessionState.LastCommandName == TEXT("release_stick"))
	{
		ApplyReleaseStick(SessionState);
	}
	else if (SessionState.LastCommandName == TEXT("execute_recipe"))
	{
		ApplyRecipe(SessionState, NormalizedArgs);
	}
	else if (SessionState.LastCommandName == TEXT("tap_button"))
	{
		SessionState.PlayerState.CurrentAction = TEXT("tap_button");
	}

	FString ExplicitTargetId;
	if (TryGetStringFieldAny(
		NormalizedArgs,
		{ TEXT("target_id"), TEXT("target_actor_id"), TEXT("current_target_id") },
		ExplicitTargetId))
	{
		ExplicitTargetId = TrimmedCopy(ExplicitTargetId);
		if (!ExplicitTargetId.IsEmpty())
		{
			if (SessionState.TargetState.ActorId != ExplicitTargetId)
			{
				SessionState.TargetState = MakeDefaultTargetState(ExplicitTargetId);
			}

			SessionState.PlayerState.CurrentTargetId = ExplicitTargetId;
		}
	}

	SyncSpatialState(SessionState);
}

void FGameTestRuntimeState::ApplyAttack(FSessionRuntimeState& SessionState, const TSharedPtr<FJsonObject>& NormalizedArgs)
{
	const FString TargetIdFromArgs = ReadStringField(NormalizedArgs, TEXT("target_id"));
	const FString ResolvedTargetId = !TargetIdFromArgs.IsEmpty()
		? TargetIdFromArgs
		: (!SessionState.PlayerState.CurrentTargetId.IsEmpty() ? SessionState.PlayerState.CurrentTargetId : SessionState.TargetState.ActorId);

	if (!ResolvedTargetId.IsEmpty() && SessionState.TargetState.ActorId != ResolvedTargetId)
	{
		SessionState.TargetState = MakeDefaultTargetState(ResolvedTargetId);
	}

	SessionState.PlayerState.CurrentTargetId = ResolvedTargetId;
	SessionState.PlayerState.CurrentAction = TEXT("attack");
	SessionState.TargetState.CurrentAction = TEXT("being_attacked");

	double DamageAmount = static_cast<double>(DefaultAttackDamage);
	double ExplicitDamage = DamageAmount;
	if (TryGetNumberFieldAny(NormalizedArgs, { TEXT("damage"), TEXT("damage_amount"), TEXT("attack_damage") }, ExplicitDamage) && ExplicitDamage > 0.0)
	{
		DamageAmount = ExplicitDamage;
	}

	const int32 AppliedDamage = FMath::Max(1, FMath::RoundToInt(DamageAmount));
	SessionState.TargetState.Health = FMath::Max(0, SessionState.TargetState.Health - AppliedDamage);
	SessionState.TargetState.bAlive = SessionState.TargetState.Health > 0;
	SessionState.TargetState.Status = SessionState.TargetState.bAlive ? TEXT("wounded") : TEXT("dead");
}

void FGameTestRuntimeState::ApplyMoveStick(FSessionRuntimeState& SessionState, const TSharedPtr<FJsonObject>& NormalizedArgs)
{
	double StickX = 0.0;
	double StickY = 0.0;
	double DurationMs = 100.0;
	(void)TryGetNumberFieldAny(NormalizedArgs, { TEXT("x"), TEXT("recommended_left_stick_x") }, StickX);
	(void)TryGetNumberFieldAny(NormalizedArgs, { TEXT("y"), TEXT("recommended_left_stick_y") }, StickY);
	(void)TryGetNumberFieldAny(NormalizedArgs, { TEXT("duration_ms") }, DurationMs);
	SetExplicitLeftStick(SessionState, StickX, StickY);

	// Runtime state keeps a lightweight kinematic approximation for state-driven flow tests.
	const double DurationSeconds = FMath::Clamp(DurationMs / 1000.0, 0.01, 2.0);
	constexpr double MoveSpeedCmPerSec = 300.0;
	const FGameTestVector3 Forward = ComputeForwardVector(SessionState.PlayerState.Rotation);
	const FGameTestVector3 Right = ComputeRightVector(SessionState.PlayerState.Rotation);
	const double DeltaX = ((Forward.X * StickY) + (Right.X * StickX)) * MoveSpeedCmPerSec * DurationSeconds;
	const double DeltaY = ((Forward.Y * StickY) + (Right.Y * StickX)) * MoveSpeedCmPerSec * DurationSeconds;
	const double DeltaZ = ((Forward.Z * StickY) + (Right.Z * StickX)) * MoveSpeedCmPerSec * DurationSeconds;
	SessionState.PlayerState.Location.X += DeltaX;
	SessionState.PlayerState.Location.Y += DeltaY;
	SessionState.PlayerState.Location.Z += DeltaZ;
	SessionState.PlayerState.CurrentAction = TEXT("move_stick");
}

void FGameTestRuntimeState::ApplyReleaseStick(FSessionRuntimeState& SessionState)
{
	SetExplicitLeftStick(SessionState, 0.0, 0.0);
	SessionState.PlayerState.CurrentAction = TEXT("release_stick");
}

void FGameTestRuntimeState::ApplyRecipe(FSessionRuntimeState& SessionState, const TSharedPtr<FJsonObject>& NormalizedArgs)
{
	const FString RecipeId = ReadStringField(NormalizedArgs, TEXT("recipe_id"));
	SessionState.PlayerState.CurrentAction = RecipeId.IsEmpty()
		? TEXT("execute_recipe")
		: FString::Printf(TEXT("recipe:%s"), *RecipeId);
}

void FGameTestRuntimeState::SetExplicitLeftStick(FSessionRuntimeState& SessionState, double X, double Y)
{
	FGameTestVector3 StickVector;
	StickVector.X = ClampStickValue(X);
	StickVector.Y = ClampStickValue(Y);
	StickVector.Z = 0.0;
	SessionState.ExplicitLeftStick = StickVector;
}

void FGameTestRuntimeState::BuildStateMetadata(TSharedRef<FJsonObject>& JsonObject, const FSessionRuntimeState& SessionState) const
{
	JsonObject->SetStringField(TEXT("session_id"), SessionState.SessionId);
	JsonObject->SetStringField(TEXT("last_command_name"), SessionState.LastCommandName);
	JsonObject->SetStringField(TEXT("last_trace_id"), SessionState.LastTraceId);
	JsonObject->SetStringField(TEXT("last_updated_utc"), SessionState.LastUpdatedUtc.ToIso8601());
}
