#include "GameTestCommandService.h"

#include "GameTestInputExecutor.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/DateTime.h"
#include "Misc/Guid.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
	FString TrimmedToLower(const FString& Value)
	{
		FString Result = Value;
		Result.TrimStartAndEndInline();
		Result = Result.ToLower();
		return Result;
	}

	TSharedRef<FJsonObject> EnsureDetailsObject(TSharedPtr<FJsonObject>& Details)
	{
		if (!Details.IsValid())
		{
			Details = MakeShared<FJsonObject>();
		}

		return Details.ToSharedRef();
	}

	TSharedRef<FJsonObject> EnsureNestedObject(TSharedPtr<FJsonObject>& Parent, const FString& FieldName)
	{
		TSharedRef<FJsonObject> ParentRef = EnsureDetailsObject(Parent);
		TSharedPtr<FJsonObject> Child;
		if (const TSharedPtr<FJsonValue>* ExistingValue = ParentRef->Values.Find(FieldName))
		{
			if (ExistingValue->IsValid() && (*ExistingValue)->Type == EJson::Object)
			{
				Child = (*ExistingValue)->AsObject();
			}
		}

		if (!Child.IsValid())
		{
			Child = MakeShared<FJsonObject>();
			ParentRef->SetObjectField(FieldName, Child);
		}

		return Child.ToSharedRef();
	}

	void SetCommandStepMetadata(
		TSharedPtr<FJsonObject>& Details,
		const FString& CommandName,
		const FString& TraceId,
		const FString& ExecutionState,
		const FString& ValidationState,
		const FString& ErrorStage,
		const FString& ImplementationStatus)
	{
		TSharedRef<FJsonObject> Root = EnsureDetailsObject(Details);
		Root->SetStringField(TEXT("command_name"), CommandName);
		Root->SetStringField(TEXT("trace_id"), TraceId);
		Root->SetStringField(TEXT("execution_state"), ExecutionState);
		Root->SetStringField(TEXT("validation_state"), ValidationState);
		Root->SetStringField(TEXT("implementation_status"), ImplementationStatus);
		Root->SetStringField(TEXT("error_stage"), ErrorStage);

		TSharedRef<FJsonObject> CommandStep = EnsureNestedObject(Details, TEXT("command_step"));
		CommandStep->SetStringField(TEXT("command_name"), CommandName);
		CommandStep->SetStringField(TEXT("trace_id"), TraceId);
		CommandStep->SetStringField(TEXT("step_name"), CommandName);
		CommandStep->SetNumberField(TEXT("step_index"), 0.0);
		CommandStep->SetStringField(TEXT("state"), ExecutionState);
		CommandStep->SetStringField(TEXT("validation_state"), ValidationState);
		CommandStep->SetStringField(TEXT("implementation_status"), ImplementationStatus);
		CommandStep->SetStringField(TEXT("error_stage"), ErrorStage);
	}

	void SetNormalizedString(TSharedPtr<FJsonObject>& Details, const FString& Key, const FString& Value)
	{
		TSharedRef<FJsonObject> Root = EnsureDetailsObject(Details);
		Root->SetStringField(Key, Value);
		EnsureNestedObject(Details, TEXT("normalized_args"))->SetStringField(Key, Value);
	}

	void SetNormalizedNumber(TSharedPtr<FJsonObject>& Details, const FString& Key, double Value)
	{
		TSharedRef<FJsonObject> Root = EnsureDetailsObject(Details);
		Root->SetNumberField(Key, Value);
		EnsureNestedObject(Details, TEXT("normalized_args"))->SetNumberField(Key, Value);
	}

	void SetNormalizedBool(TSharedPtr<FJsonObject>& Details, const FString& Key, bool Value)
	{
		TSharedRef<FJsonObject> Root = EnsureDetailsObject(Details);
		Root->SetBoolField(Key, Value);
		EnsureNestedObject(Details, TEXT("normalized_args"))->SetBoolField(Key, Value);
	}

	void SetDetailString(TSharedPtr<FJsonObject>& Details, const FString& Key, const FString& Value)
	{
		EnsureDetailsObject(Details)->SetStringField(Key, Value);
	}

	void MarkRejectedDetails(TSharedPtr<FJsonObject>& Details, const FString& CommandName, const FString& TraceId, const FString& ErrorStage, const FString& ErrorCode, const FString& ErrorMessage, const FString& ImplementationStatus = TEXT("stub"))
	{
		TSharedRef<FJsonObject> Root = EnsureDetailsObject(Details);
		SetCommandStepMetadata(Details, CommandName, TraceId, TEXT("rejected"), TEXT("rejected"), ErrorStage, ImplementationStatus);
		Root->SetStringField(TEXT("error_code"), ErrorCode);
		Root->SetStringField(TEXT("error_message"), ErrorMessage);
	}

	TSharedPtr<FJsonObject> FindObjectField(const TSharedPtr<FJsonObject>& Parent, const FString& FieldName)
	{
		if (!Parent.IsValid())
		{
			return nullptr;
		}

		const TSharedPtr<FJsonValue>* ExistingValue = Parent->Values.Find(FieldName);
		if (ExistingValue == nullptr || !ExistingValue->IsValid() || (*ExistingValue)->Type != EJson::Object)
		{
			return nullptr;
		}

		return (*ExistingValue)->AsObject();
	}

	TSharedPtr<FJsonObject> GetNormalizedArgsObject(const TSharedPtr<FJsonObject>& Details)
	{
		TSharedPtr<FJsonObject> NormalizedArgs = FindObjectField(Details, TEXT("normalized_args"));
		if (!NormalizedArgs.IsValid())
		{
			NormalizedArgs = FindObjectField(Details, TEXT("normalizedArgs"));
		}

		return NormalizedArgs;
	}

	void MergeObjectIntoRoot(TSharedPtr<FJsonObject>& Root, const FString& FieldName, const TSharedPtr<FJsonObject>& Object)
	{
		if (!Object.IsValid())
		{
			return;
		}

		EnsureDetailsObject(Root)->SetObjectField(FieldName, Object);
	}

	void SetResponseExecutionFailure(
		FGameTestCommandResponse& Response,
		const FGameTestCommandRequest& Request,
		const FString& ErrorMessage)
	{
		Response.bAccepted = false;
		Response.ErrorStage = TEXT("execution");
		Response.ErrorCode = TEXT("input_execution_failed");
		Response.ErrorMessage = ErrorMessage.IsEmpty()
			? TEXT("Native input execution failed.")
			: ErrorMessage;
		Response.ImplementationStatus = TEXT("native_input");
		SetCommandStepMetadata(
			Response.Details,
			Request.CommandName,
			Request.TraceId,
			TEXT("failed"),
			TEXT("accepted"),
			Response.ErrorStage,
			Response.ImplementationStatus);
		SetDetailString(Response.Details, TEXT("execution_state"), TEXT("failed"));
		SetDetailString(Response.Details, TEXT("validation_state"), TEXT("accepted"));
		SetDetailString(Response.Details, TEXT("error_code"), Response.ErrorCode);
		SetDetailString(Response.Details, TEXT("error_message"), Response.ErrorMessage);
	}

	void SetResponseExecutionSuccess(FGameTestCommandResponse& Response, const FGameTestCommandRequest& Request)
	{
		Response.bAccepted = true;
		Response.ErrorCode.Reset();
		Response.ErrorMessage.Reset();
		Response.ErrorStage.Reset();
		Response.ImplementationStatus = TEXT("native_input");
		SetCommandStepMetadata(
			Response.Details,
			Request.CommandName,
			Request.TraceId,
			TEXT("executed"),
			TEXT("accepted"),
			TEXT(""),
			Response.ImplementationStatus);
		SetDetailString(Response.Details, TEXT("execution_state"), TEXT("executed"));
		SetDetailString(Response.Details, TEXT("validation_state"), TEXT("accepted"));
	}

	bool TryExecuteNativeInput(const FGameTestCommandRequest& Request, FGameTestCommandResponse& Response)
	{
		const FGameTestInputExecutionRequest ExecutionRequest {
			Request.CommandName,
			Request.TraceId,
			GetNormalizedArgsObject(Response.Details)
		};

		const FGameTestInputExecutionResult ExecutionResult = FGameTestInputExecutor::ExecuteCommand(ExecutionRequest);
		MergeObjectIntoRoot(Response.Details, TEXT("input_execution"), ExecutionResult.Details);
		if (!ExecutionResult.bSucceeded)
		{
			SetResponseExecutionFailure(Response, Request, ExecutionResult.ErrorMessage);
			return false;
		}

		SetResponseExecutionSuccess(Response, Request);
		return true;
	}
}

TSharedRef<FJsonObject> FGameTestCommandResponse::ToJsonObject() const
{
	TSharedRef<FJsonObject> JsonObject = MakeShared<FJsonObject>();
	JsonObject->SetBoolField(TEXT("accepted"), bAccepted);
	JsonObject->SetStringField(TEXT("command"), CommandName);
	JsonObject->SetStringField(TEXT("trace_id"), TraceId);
	JsonObject->SetStringField(TEXT("timestamp_utc"), TimestampUtc);
	JsonObject->SetStringField(TEXT("implementation_status"), ImplementationStatus.IsEmpty() ? TEXT("stub") : ImplementationStatus);

	if (!ErrorCode.IsEmpty())
	{
		JsonObject->SetStringField(TEXT("error_code"), ErrorCode);
	}

	if (!ErrorMessage.IsEmpty())
	{
		JsonObject->SetStringField(TEXT("error_message"), ErrorMessage);
	}

	if (Details.IsValid())
	{
		JsonObject->SetObjectField(TEXT("details"), Details.ToSharedRef());
	}

	return JsonObject;
}

FString FGameTestCommandResponse::ToJsonString() const
{
	FString Output;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
	FJsonSerializer::Serialize(ToJsonObject(), Writer);
	return Output;
}

FGameTestCommandResponse FGameTestCommandService::ExecuteFromJson(const FString& RequestBodyJson)
{
	TSharedPtr<FJsonObject> RequestJson;
	if (RequestBodyJson.TrimStartAndEnd().IsEmpty())
	{
		return MakeRejected(TEXT(""), BuildTraceId(), TEXT("parse"), TEXT("invalid_json"), TEXT("Request body is empty."));
	}

	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(RequestBodyJson);
	if (!FJsonSerializer::Deserialize(Reader, RequestJson) || !RequestJson.IsValid())
	{
		return MakeRejected(TEXT(""), BuildTraceId(), TEXT("parse"), TEXT("invalid_json"), TEXT("Failed to parse request body as JSON object."));
	}

	return ExecuteFromJsonObject(RequestJson);
}

FGameTestCommandResponse FGameTestCommandService::ExecuteFromJsonObject(const TSharedPtr<FJsonObject>& RequestJson)
{
	return ParseAndValidateRequest(RequestJson);
}

FGameTestCommandResponse FGameTestCommandService::ParseAndValidateRequest(const TSharedPtr<FJsonObject>& RequestJson)
{
	FGameTestCommandRequest Request;
	FString ErrorStage;
	FString ErrorCode;
	FString ErrorMessage;

	if (!TryBuildRequest(RequestJson, Request, ErrorStage, ErrorCode, ErrorMessage))
	{
		return MakeRejected(Request.CommandName, Request.TraceId, ErrorStage, ErrorCode, ErrorMessage);
	}

	FGameTestCommandResponse Response;
	if (!TryBuildAcceptedResponse(Request, Response))
	{
		return Response;
	}

	return Response;
}

bool FGameTestCommandService::TryBuildRequest(const TSharedPtr<FJsonObject>& RequestJson, FGameTestCommandRequest& OutRequest, FString& OutErrorStage, FString& OutErrorCode, FString& OutErrorMessage)
{
	if (!RequestJson.IsValid())
	{
		OutErrorStage = TEXT("validation");
		OutErrorCode = TEXT("invalid_json");
		OutErrorMessage = TEXT("Request body must be a JSON object.");
		return false;
	}

	if (!RequestJson->TryGetStringField(TEXT("command"), OutRequest.CommandName))
	{
		OutErrorStage = TEXT("validation");
		OutErrorCode = TEXT("missing_field");
		OutErrorMessage = TEXT("command is required.");
		return false;
	}

	OutRequest.CommandName = NormalizeCommandName(OutRequest.CommandName);
	if (OutRequest.CommandName.IsEmpty())
	{
		OutErrorStage = TEXT("validation");
		OutErrorCode = TEXT("invalid_field");
		OutErrorMessage = TEXT("command must not be empty.");
		return false;
	}

	if (!RequestJson->TryGetStringField(TEXT("trace_id"), OutRequest.TraceId) || OutRequest.TraceId.TrimStartAndEnd().IsEmpty())
	{
		OutRequest.TraceId = BuildTraceId();
	}

	if (!TryBuildCommandArguments(RequestJson, OutRequest.Arguments))
	{
		OutErrorStage = TEXT("validation");
		OutErrorCode = TEXT("invalid_field");
		OutErrorMessage = TEXT("args must be a JSON object when present.");
		return false;
	}

	return true;
}

bool FGameTestCommandService::TryBuildCommandArguments(const TSharedPtr<FJsonObject>& RequestJson, TSharedPtr<FJsonObject>& OutArguments)
{
	if (const TSharedPtr<FJsonValue>* ArgsValue = RequestJson->Values.Find(TEXT("args")))
	{
		if (!ArgsValue->IsValid() || (*ArgsValue)->Type != EJson::Object)
		{
			return false;
		}

		OutArguments = (*ArgsValue)->AsObject();
		if (!OutArguments.IsValid())
		{
			return false;
		}

		return true;
	}

	OutArguments = RequestJson;
	return true;
}

bool FGameTestCommandService::TryBuildAcceptedResponse(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse)
{
	FGameTestCommandResponse Response;
	Response.bAccepted = true;
	Response.CommandName = Request.CommandName;
	Response.TraceId = Request.TraceId.IsEmpty() ? BuildTraceId() : Request.TraceId;
	Response.ErrorStage = TEXT("validation");
	Response.TimestampUtc = BuildTimestampUtc();
	Response.ImplementationStatus = TEXT("validated");
	Response.Details = MakeDetailsObject();
	SetCommandStepMetadata(
		Response.Details,
		Request.CommandName,
		Response.TraceId,
		TEXT("validated"),
		TEXT("accepted"),
		TEXT(""),
		Response.ImplementationStatus);
	SetResponseDetailsString(Response.Details, TEXT("execution_state"), TEXT("validated"));
	SetResponseDetailsString(Response.Details, TEXT("validation_state"), TEXT("accepted"));

	if (Request.CommandName == TEXT("attack"))
	{
		if (!ValidateAttack(Request, Response))
		{
			OutResponse = Response;
			return false;
		}
	}
	else if (Request.CommandName == TEXT("tap_button"))
	{
		if (!ValidateTapButton(Request, Response))
		{
			OutResponse = Response;
			return false;
		}
	}
	else if (Request.CommandName == TEXT("move_stick"))
	{
		if (!ValidateMoveStick(Request, Response))
		{
			OutResponse = Response;
			return false;
		}
	}
	else if (Request.CommandName == TEXT("release_stick"))
	{
		if (!ValidateReleaseStick(Request, Response))
		{
			OutResponse = Response;
			return false;
		}
	}
	else if (Request.CommandName == TEXT("execute_recipe"))
	{
		if (!ValidateExecuteRecipe(Request, Response))
		{
			OutResponse = Response;
			return false;
		}
	}
	else
	{
		Response.bAccepted = false;
		Response.ErrorCode = TEXT("unsupported_command");
		Response.ErrorMessage = FString::Printf(TEXT("Unsupported command: %s"), *Request.CommandName);
		Response.ErrorStage = TEXT("validation");
		MarkRejectedDetails(
			Response.Details,
			Request.CommandName,
			Response.TraceId,
			Response.ErrorStage,
			Response.ErrorCode,
			Response.ErrorMessage,
			Response.ImplementationStatus);
		SetResponseDetailsString(Response.Details, TEXT("supported_commands"), TEXT("attack,tap_button,move_stick,release_stick,execute_recipe"));
		OutResponse = Response;
		return false;
	}

	if (!TryExecuteNativeInput(Request, Response))
	{
		OutResponse = Response;
		return false;
	}

	OutResponse = Response;
	return true;
}

bool FGameTestCommandService::ValidateAttack(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse)
{
	SetNormalizedString(OutResponse.Details, TEXT("command"), TEXT("attack"));

	FString TargetId;
	if (Request.Arguments.IsValid() && Request.Arguments->TryGetStringField(TEXT("target_id"), TargetId))
	{
		TargetId.TrimStartAndEndInline();
		if (TargetId.IsEmpty())
		{
			OutResponse.bAccepted = false;
			OutResponse.ErrorCode = TEXT("invalid_field");
			OutResponse.ErrorMessage = TEXT("target_id must not be empty when provided.");
			MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
			return false;
		}

		SetNormalizedString(OutResponse.Details, TEXT("target_id"), TargetId);
		SetNormalizedString(OutResponse.Details, TEXT("target_mode"), TEXT("explicit"));
	}
	else
	{
		SetNormalizedString(OutResponse.Details, TEXT("target_id"), TEXT(""));
		SetNormalizedString(OutResponse.Details, TEXT("target_mode"), TEXT("implicit"));
	}

	return true;
}

bool FGameTestCommandService::ValidateTapButton(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse)
{
	FString ButtonId;
	if (!Request.Arguments.IsValid() || !Request.Arguments->TryGetStringField(TEXT("button_id"), ButtonId))
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("missing_field");
		OutResponse.ErrorMessage = TEXT("button_id is required.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	ButtonId.TrimStartAndEndInline();
	if (ButtonId.IsEmpty())
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("invalid_field");
		OutResponse.ErrorMessage = TEXT("button_id must not be empty.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	double DurationMs = 100.0;
	if (Request.Arguments->HasField(TEXT("duration_ms")) && (!Request.Arguments->TryGetNumberField(TEXT("duration_ms"), DurationMs) || DurationMs <= 0.0))
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("invalid_field");
		OutResponse.ErrorMessage = TEXT("duration_ms must be a positive number when provided.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	SetNormalizedString(OutResponse.Details, TEXT("button_id"), ButtonId);
	SetNormalizedNumber(OutResponse.Details, TEXT("duration_ms"), DurationMs);
	SetNormalizedString(OutResponse.Details, TEXT("input_mode"), TEXT("tap"));
	return true;
}

bool FGameTestCommandService::ValidateMoveStick(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse)
{
	FString StickId;
	double X = 0.0;
	double Y = 0.0;
	double DurationMs = 100.0;

	if (!Request.Arguments.IsValid() || !Request.Arguments->TryGetStringField(TEXT("stick_id"), StickId))
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("missing_field");
		OutResponse.ErrorMessage = TEXT("stick_id is required.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	StickId.TrimStartAndEndInline();
	if (StickId.IsEmpty())
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("invalid_field");
		OutResponse.ErrorMessage = TEXT("stick_id must not be empty.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	if (!Request.Arguments->TryGetNumberField(TEXT("x"), X) || !Request.Arguments->TryGetNumberField(TEXT("y"), Y))
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("missing_field");
		OutResponse.ErrorMessage = TEXT("x and y are required.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	if (X < -1.0 || X > 1.0 || Y < -1.0 || Y > 1.0)
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("invalid_field");
		OutResponse.ErrorMessage = TEXT("x and y must be in the range [-1, 1].");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	if (Request.Arguments->HasField(TEXT("duration_ms")) && (!Request.Arguments->TryGetNumberField(TEXT("duration_ms"), DurationMs) || DurationMs <= 0.0))
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("invalid_field");
		OutResponse.ErrorMessage = TEXT("duration_ms must be a positive number when provided.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	SetNormalizedString(OutResponse.Details, TEXT("stick_id"), StickId);
	SetNormalizedNumber(OutResponse.Details, TEXT("x"), X);
	SetNormalizedNumber(OutResponse.Details, TEXT("y"), Y);
	SetNormalizedNumber(OutResponse.Details, TEXT("duration_ms"), DurationMs);
	SetNormalizedString(OutResponse.Details, TEXT("input_mode"), TEXT("stick"));
	return true;
}

bool FGameTestCommandService::ValidateReleaseStick(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse)
{
	FString StickId;
	if (!Request.Arguments.IsValid() || !Request.Arguments->TryGetStringField(TEXT("stick_id"), StickId))
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("missing_field");
		OutResponse.ErrorMessage = TEXT("stick_id is required.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	StickId.TrimStartAndEndInline();
	if (StickId.IsEmpty())
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("invalid_field");
		OutResponse.ErrorMessage = TEXT("stick_id must not be empty.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	SetNormalizedString(OutResponse.Details, TEXT("stick_id"), StickId);
	SetNormalizedString(OutResponse.Details, TEXT("input_mode"), TEXT("release"));
	return true;
}

bool FGameTestCommandService::ValidateExecuteRecipe(const FGameTestCommandRequest& Request, FGameTestCommandResponse& OutResponse)
{
	FString RecipeId;
	if (!Request.Arguments.IsValid() || !Request.Arguments->TryGetStringField(TEXT("recipe_id"), RecipeId))
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("missing_field");
		OutResponse.ErrorMessage = TEXT("recipe_id is required.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	RecipeId.TrimStartAndEndInline();
	if (RecipeId.IsEmpty())
	{
		OutResponse.bAccepted = false;
		OutResponse.ErrorCode = TEXT("invalid_field");
		OutResponse.ErrorMessage = TEXT("recipe_id must not be empty.");
		MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
		return false;
	}

	TSharedPtr<FJsonObject> ArgsObject;
	if (const TSharedPtr<FJsonValue>* ArgsValue = Request.Arguments->Values.Find(TEXT("args")))
	{
		if (!ArgsValue->IsValid() || (*ArgsValue)->Type != EJson::Object)
		{
			OutResponse.bAccepted = false;
			OutResponse.ErrorCode = TEXT("invalid_field");
			OutResponse.ErrorMessage = TEXT("args must be a JSON object when provided.");
			MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
			return false;
		}

		ArgsObject = (*ArgsValue)->AsObject();
		if (!ArgsObject.IsValid())
		{
			OutResponse.bAccepted = false;
			OutResponse.ErrorCode = TEXT("invalid_field");
			OutResponse.ErrorMessage = TEXT("args must be a JSON object when provided.");
			MarkRejectedDetails(OutResponse.Details, Request.CommandName, Request.TraceId, TEXT("validation"), OutResponse.ErrorCode, OutResponse.ErrorMessage);
			return false;
		}
	}

	SetNormalizedString(OutResponse.Details, TEXT("recipe_id"), RecipeId);
	if (ArgsObject.IsValid())
	{
		SetNormalizedString(OutResponse.Details, TEXT("args_state"), TEXT("present"));
	}
	else
	{
		SetNormalizedString(OutResponse.Details, TEXT("args_state"), TEXT("empty"));
	}

	return true;
}

FString FGameTestCommandService::BuildTraceId()
{
	return FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphensLower);
}

FString FGameTestCommandService::BuildTimestampUtc()
{
	return FDateTime::UtcNow().ToIso8601();
}

FString FGameTestCommandService::NormalizeCommandName(const FString& CommandName)
{
	return TrimmedToLower(CommandName);
}

FGameTestCommandResponse FGameTestCommandService::MakeRejected(const FString& CommandName, const FString& TraceId, const FString& ErrorStage, const FString& ErrorCode, const FString& ErrorMessage, const TSharedPtr<FJsonObject>& Details)
{
	FGameTestCommandResponse Response;
	Response.bAccepted = false;
	Response.CommandName = CommandName;
	Response.TraceId = TraceId.IsEmpty() ? BuildTraceId() : TraceId;
	Response.ErrorStage = ErrorStage;
	Response.ErrorCode = ErrorCode;
	Response.ErrorMessage = ErrorMessage;
	Response.TimestampUtc = BuildTimestampUtc();
	Response.ImplementationStatus = TEXT("stub");
	Response.Details = Details.IsValid() ? Details : MakeDetailsObject();
	MarkRejectedDetails(Response.Details, Response.CommandName, Response.TraceId, ErrorStage, ErrorCode, ErrorMessage, Response.ImplementationStatus);
	return Response;
}

void FGameTestCommandService::SetResponseDetailsString(TSharedPtr<FJsonObject>& Details, const FString& Key, const FString& Value)
{
	if (!Details.IsValid())
	{
		Details = MakeDetailsObject();
	}

	Details->SetStringField(Key, Value);
}

void FGameTestCommandService::SetResponseDetailsNumber(TSharedPtr<FJsonObject>& Details, const FString& Key, double Value)
{
	if (!Details.IsValid())
	{
		Details = MakeDetailsObject();
	}

	Details->SetNumberField(Key, Value);
}

TSharedPtr<FJsonObject> FGameTestCommandService::MakeDetailsObject()
{
	return MakeShared<FJsonObject>();
}
