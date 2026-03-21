#pragma once

#include "CoreMinimal.h"
#include "GameTestEventRecorder.h"
#include "GameTestRuntimeState.h"
#include "HttpServerRequest.h"
#include "HttpServerResponse.h"
#include "IHttpRouter.h"

#include "GameTestSessionManager.h"

class FJsonObject;
class FGameTestWebSocketServer;

class FGameTestRemoteServer
{
public:
	FGameTestRemoteServer();
	~FGameTestRemoteServer();

	bool Start(uint16 InPort);
	void Stop();
	bool IsRunning() const;
	uint16 GetPort() const;

private:
	bool BindRoutes();
	void UnbindRoutes();

	bool HandleHealth(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
	bool HandleCapabilities(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
	bool HandleSessionStart(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
	bool HandleSessionStop(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
	bool HandleCommandExecute(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
	bool HandlePlayerState(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
	bool HandleTargetState(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
	bool HandleSpatialState(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
	bool HandleEvents(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
	void HandleRecordedEvent(const FGameTestEventRecord& Event);

	static bool ParseRequestJson(const FHttpServerRequest& Request, TSharedPtr<FJsonObject>& OutJson, FString& OutError);
	static TUniquePtr<FHttpServerResponse> MakeJsonResponse(EHttpServerResponseCodes ResponseCode, const TSharedRef<FJsonObject>& JsonBody);
	static TSharedRef<FJsonObject> MakeErrorJson(const FString& ErrorCode, const FString& Message);
	static FString ReadStringFieldOrDefault(const TSharedPtr<FJsonObject>& Json, const FString& FieldName, const FString& DefaultValue = TEXT(""));
	bool TryGetSessionIdFromQuery(const FHttpServerRequest& Request, FString& OutSessionId) const;
	FString BuildWebSocketUrl() const;
	bool StartWebSocketStream();
	void StopWebSocketStream();

private:
	uint16 ListeningPort;
	uint16 WebSocketPort;
	bool bRunning;

	TSharedPtr<IHttpRouter> HttpRouter;
	TArray<FHttpRouteHandle> RouteHandles;
	FGameTestSessionManager SessionManager;
	FGameTestEventRecorder EventRecorder;
	FGameTestRuntimeState RuntimeState;
	FDelegateHandle EventRecordedHandle;
	TUniquePtr<FGameTestWebSocketServer> WebSocketServer;
};
