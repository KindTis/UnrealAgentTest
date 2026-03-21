#pragma once

#include "CoreMinimal.h"

class FJsonObject;
struct FGameTestEventRecord;

DECLARE_MULTICAST_DELEGATE_OneParam(FGameTestEventRecordedDelegate, const FGameTestEventRecord&);

struct FGameTestEventRecord
{
	FString SessionId;
	FString TraceId;
	int64 SequenceId = 0;
	FDateTime TimestampUtc;
	FString Type;
	TSharedPtr<FJsonObject> Payload;
};

class FGameTestEventRecorder
{
public:
	explicit FGameTestEventRecorder(int32 InMaxEventsPerSession = 128);

	FDelegateHandle AddEventRecordedListener(const FGameTestEventRecordedDelegate::FDelegate& Delegate);
	void RemoveEventRecordedListener(FDelegateHandle Handle);

	FGameTestEventRecord RecordCommandAccepted(const FString& SessionId, const FString& TraceId, const FString& CommandName, const TSharedPtr<FJsonObject>& Payload = nullptr);
	FGameTestEventRecord RecordCommandRejected(const FString& SessionId, const FString& TraceId, const FString& CommandName, const FString& Reason, const TSharedPtr<FJsonObject>& Payload = nullptr);
	FGameTestEventRecord RecordError(const FString& SessionId, const FString& TraceId, const FString& ErrorCode, const FString& Message, const TSharedPtr<FJsonObject>& Payload = nullptr);
	FGameTestEventRecord RecordCustomEvent(const FString& SessionId, const FString& TraceId, const FString& Type, const TSharedPtr<FJsonObject>& Payload = nullptr);
	FGameTestEventRecord RecordCommandStepStarted(const FString& SessionId, const FString& TraceId, const FString& CommandName, int32 StepIndex, const FString& StepName = FString(), const TSharedPtr<FJsonObject>& Payload = nullptr);
	FGameTestEventRecord RecordCommandStepSucceeded(const FString& SessionId, const FString& TraceId, const FString& CommandName, int32 StepIndex, const FString& StepName = FString(), const TSharedPtr<FJsonObject>& Payload = nullptr);
	FGameTestEventRecord RecordCommandStepFailed(const FString& SessionId, const FString& TraceId, const FString& CommandName, int32 StepIndex, const FString& ErrorCode, const FString& ErrorMessage, const FString& StepName = FString(), const TSharedPtr<FJsonObject>& Payload = nullptr);

	TArray<FGameTestEventRecord> GetRecentEvents(const FString& SessionId, const FString& TypeFilter = FString(), int32 Limit = 0, int64 AfterSequence = 0) const;
	TSharedRef<FJsonObject> GetRecentEventsJson(const FString& SessionId, const FString& TypeFilter = FString(), int32 Limit = 0, int64 AfterSequence = 0) const;
	void ClearSession(const FString& SessionId);

private:
	struct FSessionEventBuffer
	{
		TArray<FGameTestEventRecord> Events;
		int64 NextSequenceId = 1;
		int64 LastSequenceId = 0;
	};

	FGameTestEventRecord RecordEvent(const FString& SessionId, const FString& TraceId, const FString& Type, const TSharedPtr<FJsonObject>& Payload);
	int64 GetLastSequenceId(const FString& SessionId) const;
	TSharedPtr<FJsonObject> MakeCommandStepPayload(const FString& CommandName, int32 StepIndex, const FString& StepName, const FString& Result, const TSharedPtr<FJsonObject>& Payload, const FString& ErrorCode = FString(), const FString& ErrorMessage = FString()) const;
	TSharedRef<FJsonObject> MakeEventJson(const FGameTestEventRecord& Event) const;
	TSharedPtr<FJsonObject> MakePayloadObject(const TSharedPtr<FJsonObject>& Payload) const;

private:
	mutable FCriticalSection RecorderLock;
	TMap<FString, FSessionEventBuffer> SessionBuffers;
	int32 MaxEventsPerSession;
	FGameTestEventRecordedDelegate EventRecordedDelegate;
};
