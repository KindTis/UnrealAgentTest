#include "GameTestSessionManager.h"

#include "Misc/DateTime.h"
#include "Misc/Guid.h"
#include "Misc/ScopeLock.h"

FGameTestSessionRecord FGameTestSessionManager::StartSession(const FString& RequestedSessionId, const FString& RequestedRunId)
{
	const FString SessionId = RequestedSessionId.IsEmpty()
		? FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphensLower)
		: RequestedSessionId;
	const FDateTime StartedAtUtc = FDateTime::UtcNow();
	const FString RunId = RequestedRunId.IsEmpty()
		? StartedAtUtc.ToString(TEXT("%Y%m%dT%H%M%SZ"))
		: RequestedRunId;

	FGameTestSessionRecord SessionRecord;
	SessionRecord.SessionId = SessionId;
	SessionRecord.RunId = RunId;
	SessionRecord.StartedAtUtc = StartedAtUtc;

	FScopeLock Lock(&SessionsLock);
	ActiveSessions.Add(SessionId, SessionRecord);
	return SessionRecord;
}

bool FGameTestSessionManager::StopSession(const FString& SessionId)
{
	if (SessionId.IsEmpty())
	{
		return false;
	}

	FScopeLock Lock(&SessionsLock);
	return ActiveSessions.Remove(SessionId) > 0;
}

bool FGameTestSessionManager::HasSession(const FString& SessionId) const
{
	if (SessionId.IsEmpty())
	{
		return false;
	}

	FScopeLock Lock(&SessionsLock);
	return ActiveSessions.Contains(SessionId);
}

int32 FGameTestSessionManager::GetActiveSessionCount() const
{
	FScopeLock Lock(&SessionsLock);
	return ActiveSessions.Num();
}

TArray<FGameTestSessionRecord> FGameTestSessionManager::GetActiveSessions() const
{
	TArray<FGameTestSessionRecord> Sessions;

	FScopeLock Lock(&SessionsLock);
	ActiveSessions.GenerateValueArray(Sessions);
	return Sessions;
}
