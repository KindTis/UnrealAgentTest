#pragma once

#include "CoreMinimal.h"

struct FGameTestSessionRecord
{
	FString SessionId;
	FString RunId;
	FDateTime StartedAtUtc;
};

class FGameTestSessionManager
{
public:
	FGameTestSessionRecord StartSession(const FString& RequestedSessionId, const FString& RequestedRunId);
	bool StopSession(const FString& SessionId);
	bool HasSession(const FString& SessionId) const;
	int32 GetActiveSessionCount() const;
	TArray<FGameTestSessionRecord> GetActiveSessions() const;

private:
	mutable FCriticalSection SessionsLock;
	TMap<FString, FGameTestSessionRecord> ActiveSessions;
};
