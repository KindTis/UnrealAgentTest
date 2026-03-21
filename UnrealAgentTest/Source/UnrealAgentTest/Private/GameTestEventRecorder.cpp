#include "GameTestEventRecorder.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/DateTime.h"
#include "Misc/Guid.h"
#include "Misc/ScopeLock.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	FString EnsureTraceId(const FString& TraceId)
	{
		return TraceId.IsEmpty()
			? FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphensLower)
			: TraceId;
	}
}

FGameTestEventRecorder::FGameTestEventRecorder(int32 InMaxEventsPerSession)
	: MaxEventsPerSession(FMath::Max(1, InMaxEventsPerSession))
{
}

FDelegateHandle FGameTestEventRecorder::AddEventRecordedListener(const FGameTestEventRecordedDelegate::FDelegate& Delegate)
{
	return EventRecordedDelegate.Add(Delegate);
}

void FGameTestEventRecorder::RemoveEventRecordedListener(FDelegateHandle Handle)
{
	EventRecordedDelegate.Remove(Handle);
}

FGameTestEventRecord FGameTestEventRecorder::RecordCommandAccepted(const FString& SessionId, const FString& TraceId, const FString& CommandName, const TSharedPtr<FJsonObject>& Payload)
{
	TSharedPtr<FJsonObject> EventPayload = MakeShared<FJsonObject>();
	EventPayload->SetStringField(TEXT("command_name"), CommandName);
	EventPayload->SetStringField(TEXT("result"), TEXT("accepted"));
	if (Payload.IsValid())
	{
		EventPayload->SetObjectField(TEXT("details"), Payload);
	}
	return RecordEvent(SessionId, TraceId, TEXT("command_accepted"), EventPayload);
}

FGameTestEventRecord FGameTestEventRecorder::RecordCommandRejected(const FString& SessionId, const FString& TraceId, const FString& CommandName, const FString& Reason, const TSharedPtr<FJsonObject>& Payload)
{
	TSharedPtr<FJsonObject> EventPayload = MakeShared<FJsonObject>();
	EventPayload->SetStringField(TEXT("command_name"), CommandName);
	EventPayload->SetStringField(TEXT("reason"), Reason);
	EventPayload->SetStringField(TEXT("result"), TEXT("rejected"));
	if (Payload.IsValid())
	{
		EventPayload->SetObjectField(TEXT("details"), Payload);
	}
	return RecordEvent(SessionId, TraceId, TEXT("command_rejected"), EventPayload);
}

FGameTestEventRecord FGameTestEventRecorder::RecordError(const FString& SessionId, const FString& TraceId, const FString& ErrorCode, const FString& Message, const TSharedPtr<FJsonObject>& Payload)
{
	TSharedPtr<FJsonObject> EventPayload = MakeShared<FJsonObject>();
	EventPayload->SetStringField(TEXT("error_code"), ErrorCode);
	EventPayload->SetStringField(TEXT("message"), Message);
	if (Payload.IsValid())
	{
		EventPayload->SetObjectField(TEXT("details"), Payload);
	}
	return RecordEvent(SessionId, TraceId, TEXT("error"), EventPayload);
}

FGameTestEventRecord FGameTestEventRecorder::RecordCustomEvent(const FString& SessionId, const FString& TraceId, const FString& Type, const TSharedPtr<FJsonObject>& Payload)
{
	const FString EventType = Type.TrimStartAndEnd();
	if (EventType.IsEmpty())
	{
		return RecordEvent(SessionId, TraceId, TEXT("error"), MakeShared<FJsonObject>());
	}

	return RecordEvent(SessionId, TraceId, EventType, Payload);
}

FGameTestEventRecord FGameTestEventRecorder::RecordCommandStepStarted(const FString& SessionId, const FString& TraceId, const FString& CommandName, int32 StepIndex, const FString& StepName, const TSharedPtr<FJsonObject>& Payload)
{
	return RecordEvent(SessionId, TraceId, TEXT("command_step_started"), MakeCommandStepPayload(CommandName, StepIndex, StepName, TEXT("started"), Payload));
}

FGameTestEventRecord FGameTestEventRecorder::RecordCommandStepSucceeded(const FString& SessionId, const FString& TraceId, const FString& CommandName, int32 StepIndex, const FString& StepName, const TSharedPtr<FJsonObject>& Payload)
{
	return RecordEvent(SessionId, TraceId, TEXT("command_step_succeeded"), MakeCommandStepPayload(CommandName, StepIndex, StepName, TEXT("succeeded"), Payload));
}

FGameTestEventRecord FGameTestEventRecorder::RecordCommandStepFailed(const FString& SessionId, const FString& TraceId, const FString& CommandName, int32 StepIndex, const FString& ErrorCode, const FString& ErrorMessage, const FString& StepName, const TSharedPtr<FJsonObject>& Payload)
{
	return RecordEvent(SessionId, TraceId, TEXT("command_step_failed"), MakeCommandStepPayload(CommandName, StepIndex, StepName, TEXT("failed"), Payload, ErrorCode, ErrorMessage));
}

TArray<FGameTestEventRecord> FGameTestEventRecorder::GetRecentEvents(const FString& SessionId, const FString& TypeFilter, int32 Limit, int64 AfterSequence) const
{
	FScopeLock Lock(&RecorderLock);

	const FSessionEventBuffer* Buffer = SessionBuffers.Find(SessionId);
	if (Buffer == nullptr)
	{
		return {};
	}

	TArray<FGameTestEventRecord> FilteredEvents;
	FilteredEvents.Reserve(Buffer->Events.Num());

	for (const FGameTestEventRecord& Event : Buffer->Events)
	{
		if (AfterSequence > 0 && Event.SequenceId <= AfterSequence)
		{
			continue;
		}

		if (!TypeFilter.IsEmpty() && !Event.Type.Equals(TypeFilter, ESearchCase::IgnoreCase))
		{
			continue;
		}

		FilteredEvents.Add(Event);
	}

	if (Limit > 0 && FilteredEvents.Num() > Limit)
	{
		const int32 StartIndex = FilteredEvents.Num() - Limit;
		TArray<FGameTestEventRecord> LimitedEvents;
		LimitedEvents.Append(FilteredEvents.GetData() + StartIndex, Limit);
		return LimitedEvents;
	}

	return FilteredEvents;
}

TSharedRef<FJsonObject> FGameTestEventRecorder::GetRecentEventsJson(const FString& SessionId, const FString& TypeFilter, int32 Limit, int64 AfterSequence) const
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	Json->SetStringField(TEXT("session_id"), SessionId);
	Json->SetStringField(TEXT("timestamp"), FDateTime::UtcNow().ToIso8601());
	if (AfterSequence > 0)
	{
		Json->SetNumberField(TEXT("after_sequence"), static_cast<double>(AfterSequence));
	}
	if (!TypeFilter.IsEmpty())
	{
		Json->SetStringField(TEXT("type_filter"), TypeFilter);
	}
	if (Limit > 0)
	{
		Json->SetNumberField(TEXT("limit"), Limit);
	}

	TArray<TSharedPtr<FJsonValue>> EventValues;
	const TArray<FGameTestEventRecord> Events = GetRecentEvents(SessionId, TypeFilter, Limit, AfterSequence);
	for (const FGameTestEventRecord& Event : Events)
	{
		EventValues.Add(MakeShared<FJsonValueObject>(MakeEventJson(Event)));
	}

	Json->SetArrayField(TEXT("events"), EventValues);
	Json->SetNumberField(TEXT("last_sequence"), static_cast<double>(GetLastSequenceId(SessionId)));
	return Json;
}

void FGameTestEventRecorder::ClearSession(const FString& SessionId)
{
	FScopeLock Lock(&RecorderLock);
	SessionBuffers.Remove(SessionId);
}

FGameTestEventRecord FGameTestEventRecorder::RecordEvent(const FString& SessionId, const FString& TraceId, const FString& Type, const TSharedPtr<FJsonObject>& Payload)
{
	FGameTestEventRecord Event;
	Event.SessionId = SessionId;
	Event.TraceId = EnsureTraceId(TraceId);
	Event.SequenceId = 0;
	Event.TimestampUtc = FDateTime::UtcNow();
	Event.Type = Type;
	Event.Payload = MakePayloadObject(Payload);

	FScopeLock Lock(&RecorderLock);
	FSessionEventBuffer& Buffer = SessionBuffers.FindOrAdd(SessionId);
	Event.SequenceId = Buffer.NextSequenceId++;
	Buffer.LastSequenceId = Event.SequenceId;
	Buffer.Events.Add(Event);

	if (Buffer.Events.Num() > MaxEventsPerSession)
	{
		const int32 ExcessCount = Buffer.Events.Num() - MaxEventsPerSession;
		Buffer.Events.RemoveAt(0, ExcessCount, EAllowShrinking::No);
	}

	EventRecordedDelegate.Broadcast(Event);
	return Event;
}

TSharedPtr<FJsonObject> FGameTestEventRecorder::MakeCommandStepPayload(const FString& CommandName, int32 StepIndex, const FString& StepName, const FString& Result, const TSharedPtr<FJsonObject>& Payload, const FString& ErrorCode, const FString& ErrorMessage) const
{
	TSharedPtr<FJsonObject> EventPayload = MakeShared<FJsonObject>();
	EventPayload->SetStringField(TEXT("command_name"), CommandName);
	EventPayload->SetNumberField(TEXT("step_index"), StepIndex);
	EventPayload->SetStringField(TEXT("result"), Result);

	if (!StepName.IsEmpty())
	{
		EventPayload->SetStringField(TEXT("step_name"), StepName);
	}

	if (!ErrorCode.IsEmpty())
	{
		EventPayload->SetStringField(TEXT("error_code"), ErrorCode);
	}

	if (!ErrorMessage.IsEmpty())
	{
		EventPayload->SetStringField(TEXT("error_message"), ErrorMessage);
	}

	if (Payload.IsValid())
	{
		EventPayload->SetObjectField(TEXT("details"), Payload);
	}

	return EventPayload;
}

TSharedRef<FJsonObject> FGameTestEventRecorder::MakeEventJson(const FGameTestEventRecord& Event) const
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	Json->SetStringField(TEXT("session_id"), Event.SessionId);
	Json->SetStringField(TEXT("trace_id"), Event.TraceId);
	Json->SetNumberField(TEXT("sequence_id"), static_cast<double>(Event.SequenceId));
	Json->SetStringField(TEXT("timestamp"), Event.TimestampUtc.ToIso8601());
	Json->SetStringField(TEXT("type"), Event.Type);
	Json->SetObjectField(TEXT("payload"), MakePayloadObject(Event.Payload));
	return Json;
}

int64 FGameTestEventRecorder::GetLastSequenceId(const FString& SessionId) const
{
	FScopeLock Lock(&RecorderLock);
	const FSessionEventBuffer* Buffer = SessionBuffers.Find(SessionId);
	return Buffer != nullptr ? Buffer->LastSequenceId : 0;
}

TSharedPtr<FJsonObject> FGameTestEventRecorder::MakePayloadObject(const TSharedPtr<FJsonObject>& Payload) const
{
	return Payload.IsValid() ? Payload : MakeShared<FJsonObject>();
}
