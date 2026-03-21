#include "GameTestQueryService.h"

#include "Dom/JsonObject.h"
#include "Misc/DateTime.h"
#include "Misc/Guid.h"

namespace
{
	void SetOptionalNumberField(const TSharedRef<FJsonObject>& Json, const FString& FieldName, const TOptional<double>& Value)
	{
		if (Value.IsSet())
		{
			Json->SetNumberField(FieldName, Value.GetValue());
		}
	}

	void SetOptionalBoolField(const TSharedRef<FJsonObject>& Json, const FString& FieldName, const TOptional<bool>& Value)
	{
		if (Value.IsSet())
		{
			Json->SetBoolField(FieldName, Value.GetValue());
		}
	}

	void SetOptionalVectorField(const TSharedRef<FJsonObject>& Json, const FString& FieldName, const TOptional<FGameTestVector3>& Value)
	{
		if (Value.IsSet())
		{
			TSharedRef<FJsonObject> VectorJson = MakeShared<FJsonObject>();
			VectorJson->SetNumberField(TEXT("x"), Value->X);
			VectorJson->SetNumberField(TEXT("y"), Value->Y);
			VectorJson->SetNumberField(TEXT("z"), Value->Z);
			Json->SetObjectField(FieldName, VectorJson);
		}
	}
}

FString FGameTestQueryService::CreateTraceId()
{
	return FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphensLower);
}

TSharedRef<FJsonObject> FGameTestQueryService::BuildPlayerStateJson(const FGameTestActorStateInput& State)
{
	return BuildActorStateJson(State, TEXT("player"));
}

TSharedRef<FJsonObject> FGameTestQueryService::BuildTargetStateJson(const FGameTestActorStateInput& State)
{
	return BuildActorStateJson(State, TEXT("target"));
}

TSharedRef<FJsonObject> FGameTestQueryService::BuildSpatialStateJson(const FGameTestSpatialStateInput& State)
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	Json->SetStringField(TEXT("type"), TEXT("spatial_state"));
	Json->SetStringField(TEXT("timestamp"), FDateTime::UtcNow().ToIso8601());

	if (!State.SessionId.IsEmpty())
	{
		Json->SetStringField(TEXT("session_id"), State.SessionId);
	}

	if (!State.TraceId.IsEmpty())
	{
		Json->SetStringField(TEXT("trace_id"), State.TraceId);
	}

	if (!State.PlayerActorId.IsEmpty())
	{
		Json->SetStringField(TEXT("player_actor_id"), State.PlayerActorId);
	}

	if (!State.TargetActorId.IsEmpty())
	{
		Json->SetStringField(TEXT("target_actor_id"), State.TargetActorId);
	}

	SetOptionalVectorField(Json, TEXT("player_location"), State.PlayerLocation);
	SetOptionalVectorField(Json, TEXT("target_location"), State.TargetLocation);
	SetOptionalVectorField(Json, TEXT("direction_to_target"), State.DirectionToTarget);
	SetOptionalVectorField(Json, TEXT("player_forward_vector"), State.PlayerForwardVector);
	SetOptionalVectorField(Json, TEXT("target_forward_vector"), State.TargetForwardVector);
	SetOptionalNumberField(Json, TEXT("distance_cm"), State.DistanceCm);
	SetOptionalNumberField(Json, TEXT("yaw_delta_degrees"), State.YawDeltaDegrees);
	SetOptionalNumberField(Json, TEXT("recommended_left_stick_x"), State.RecommendedLeftStickX);
	SetOptionalNumberField(Json, TEXT("recommended_left_stick_y"), State.RecommendedLeftStickY);
	SetOptionalNumberField(Json, TEXT("navigation_path_length_cm"), State.NavigationPathLengthCm);
	SetOptionalBoolField(Json, TEXT("line_of_sight"), State.bLineOfSight);
	SetOptionalBoolField(Json, TEXT("target_in_attack_range"), State.bTargetInAttackRange);

	return Json;
}

TSharedRef<FJsonObject> FGameTestQueryService::BuildSpatialStateJson(
	const FString& PlayerActorId,
	const FString& TargetActorId,
	const FGameTestVector3& PlayerLocation,
	const FGameTestVector3& TargetLocation,
	double DistanceCm,
	double YawDeltaDegrees,
	double RecommendedLeftStickX,
	double RecommendedLeftStickY,
	bool bLineOfSight,
	bool bTargetInAttackRange)
{
	FGameTestSpatialStateInput State;
	State.PlayerActorId = PlayerActorId;
	State.TargetActorId = TargetActorId;
	State.PlayerLocation = PlayerLocation;
	State.TargetLocation = TargetLocation;
	State.DistanceCm = DistanceCm;
	State.YawDeltaDegrees = YawDeltaDegrees;
	State.RecommendedLeftStickX = RecommendedLeftStickX;
	State.RecommendedLeftStickY = RecommendedLeftStickY;
	State.bLineOfSight = bLineOfSight;
	State.bTargetInAttackRange = bTargetInAttackRange;
	return BuildSpatialStateJson(State);
}

TSharedRef<FJsonObject> FGameTestQueryService::BuildActorStateJson(const FGameTestActorStateInput& State, const FString& Role)
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	Json->SetStringField(TEXT("type"), Role + TEXT("_state"));
	Json->SetStringField(TEXT("timestamp"), FDateTime::UtcNow().ToIso8601());
	Json->SetStringField(TEXT("actor_id"), State.ActorId);
	Json->SetBoolField(TEXT("alive"), State.bAlive);
	Json->SetNumberField(TEXT("health"), State.Health);
	Json->SetNumberField(TEXT("max_health"), State.MaxHealth);
	Json->SetObjectField(TEXT("location"), MakeVectorJson(State.Location));
	Json->SetObjectField(TEXT("rotation"), MakeRotatorJson(State.Rotation));
	Json->SetStringField(TEXT("status"), State.Status);
	Json->SetStringField(TEXT("current_target_id"), State.CurrentTargetId);
	Json->SetStringField(TEXT("equipped_weapon_id"), State.EquippedWeaponId);
	Json->SetStringField(TEXT("current_action"), State.CurrentAction);
	Json->SetStringField(TEXT("team_id"), State.TeamId);
	return Json;
}

TSharedRef<FJsonObject> FGameTestQueryService::MakeVectorJson(const FGameTestVector3& Vector)
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	Json->SetNumberField(TEXT("x"), Vector.X);
	Json->SetNumberField(TEXT("y"), Vector.Y);
	Json->SetNumberField(TEXT("z"), Vector.Z);
	return Json;
}

TSharedRef<FJsonObject> FGameTestQueryService::MakeRotatorJson(const FGameTestRotator& Rotator)
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	Json->SetNumberField(TEXT("pitch"), Rotator.Pitch);
	Json->SetNumberField(TEXT("yaw"), Rotator.Yaw);
	Json->SetNumberField(TEXT("roll"), Rotator.Roll);
	return Json;
}
