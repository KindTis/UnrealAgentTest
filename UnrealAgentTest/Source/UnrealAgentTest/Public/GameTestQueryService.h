#pragma once

#include "CoreMinimal.h"
#include "Misc/Optional.h"

class FJsonObject;

struct FGameTestVector3
{
	double X = 0.0;
	double Y = 0.0;
	double Z = 0.0;
};

struct FGameTestRotator
{
	double Pitch = 0.0;
	double Yaw = 0.0;
	double Roll = 0.0;
};

struct FGameTestActorStateInput
{
	FString ActorId;
	bool bAlive = true;
	int32 Health = 100;
	int32 MaxHealth = 100;
	FGameTestVector3 Location;
	FGameTestRotator Rotation;
	FString Status;
	FString CurrentTargetId;
	FString EquippedWeaponId;
	FString CurrentAction;
	FString TeamId;
};

struct FGameTestSpatialStateInput
{
	FString SessionId;
	FString TraceId;
	FString PlayerActorId;
	FString TargetActorId;
	TOptional<FGameTestVector3> PlayerLocation;
	TOptional<FGameTestVector3> TargetLocation;
	TOptional<FGameTestVector3> DirectionToTarget;
	TOptional<FGameTestVector3> PlayerForwardVector;
	TOptional<FGameTestVector3> TargetForwardVector;
	TOptional<double> DistanceCm;
	TOptional<double> YawDeltaDegrees;
	TOptional<double> RecommendedLeftStickX;
	TOptional<double> RecommendedLeftStickY;
	TOptional<double> NavigationPathLengthCm;
	TOptional<bool> bLineOfSight;
	TOptional<bool> bTargetInAttackRange;
};

class FGameTestQueryService
{
public:
	static FString CreateTraceId();

	static TSharedRef<FJsonObject> BuildPlayerStateJson(const FGameTestActorStateInput& State);
	static TSharedRef<FJsonObject> BuildTargetStateJson(const FGameTestActorStateInput& State);
	static TSharedRef<FJsonObject> BuildSpatialStateJson(const FGameTestSpatialStateInput& State);

	static TSharedRef<FJsonObject> BuildSpatialStateJson(
		const FString& PlayerActorId,
		const FString& TargetActorId,
		const FGameTestVector3& PlayerLocation,
		const FGameTestVector3& TargetLocation,
		double DistanceCm,
		double YawDeltaDegrees,
		double RecommendedLeftStickX,
		double RecommendedLeftStickY,
		bool bLineOfSight,
		bool bTargetInAttackRange);

private:
	static TSharedRef<FJsonObject> BuildActorStateJson(const FGameTestActorStateInput& State, const FString& Role);
	static TSharedRef<FJsonObject> MakeVectorJson(const FGameTestVector3& Vector);
	static TSharedRef<FJsonObject> MakeRotatorJson(const FGameTestRotator& Rotator);
};
