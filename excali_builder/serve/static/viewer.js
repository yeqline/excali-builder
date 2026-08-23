import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Excalidraw } from "https://esm.sh/@excalidraw/excalidraw@0.18.0/dist/prod/index.js?external=react,react-dom";

const SAVE_DEBOUNCE_MS = 800;
const PLACEMENT_CONTEXT_DEBOUNCE_MS = 250;
const WHEEL_ZOOM_SPEED = 0.001;
const MAX_WHEEL_ZOOM_DELTA = 100;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 30;

function normalizeScene(scene, preserveAppState) {
  const nextAppState = {
    ...(scene.appState || {}),
    viewBackgroundColor: scene.appState?.viewBackgroundColor || "#ffffff",
  };

  if (preserveAppState) {
    for (const key of ["scrollX", "scrollY", "zoom"]) {
      if (preserveAppState[key] !== undefined) {
        nextAppState[key] = preserveAppState[key];
      }
    }
  }

  return {
    elements: scene.elements || [],
    appState: nextAppState,
    files: scene.files || {},
    scrollToContent: !preserveAppState,
  };
}

function statusLabel(status, detail) {
  if (!detail) {
    return status;
  }
  return `${status} ${detail}`;
}

function App() {
  const [scene, setScene] = useState(null);
  const [status, setStatus] = useState("loading");
  const [detail, setDetail] = useState("");
  const [api, setApi] = useState(null);
  const saveTimerRef = useRef(null);
  const placementTimerRef = useRef(null);
  const pointerRef = useRef(null);
  const appStateRef = useRef(null);
  const applyingRemoteRef = useRef(false);
  const hasMountedSceneRef = useRef(false);
  const lastLayoutSignatureRef = useRef("");

  const loadDiagram = useCallback(
    async (preserveViewport) => {
      const response = await fetch("/diagram", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`diagram request failed: ${response.status}`);
      }
      const rawScene = await response.json();
      const currentAppState = preserveViewport && api?.getAppState
        ? api.getAppState()
        : null;
      const nextScene = normalizeScene(rawScene, currentAppState);
      lastLayoutSignatureRef.current = layoutSignature(nextScene.elements);

      if (api) {
        applyingRemoteRef.current = true;
        if (nextScene.files && api.addFiles) {
          api.addFiles(Object.values(nextScene.files));
        }
        api.updateScene({
          elements: nextScene.elements,
          appState: nextScene.appState,
        });
        window.setTimeout(() => {
          applyingRemoteRef.current = false;
        }, 250);
      } else {
        setScene(nextScene);
      }

      setStatus("built");
      setDetail("");
    },
    [api],
  );

  useEffect(() => {
    loadDiagram(false).catch((error) => {
      console.error(error);
      setStatus("error");
      setDetail(error.message);
    });
  }, [loadDiagram]);

  useEffect(() => {
    const events = new EventSource("/events");
    events.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "rebuilding") {
        setStatus("rebuilding");
        setDetail("");
      } else if (message.type === "saving-layout") {
        setStatus("saving layout");
        setDetail("");
      } else if (message.type === "layout-saved") {
        setStatus("layout saved");
        setDetail(message.saved_count ? `(${message.saved_count})` : "");
      } else if (message.type === "built") {
        loadDiagram(true).catch((error) => {
          console.error(error);
          setStatus("error");
          setDetail(error.message);
        });
      } else if (message.type === "error") {
        setStatus("error");
        setDetail(message.message || "");
      }
    };
    events.onerror = () => {
      setStatus("error");
      setDetail("connection lost");
    };
    return () => events.close();
  }, [loadDiagram]);

  const saveLayout = useCallback(async (elements) => {
    setStatus("saving layout");
    setDetail("");
    const response = await fetch("/layout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ elements }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `layout save failed: ${response.status}`);
    }
    const payload = await response.json();
    setStatus("layout saved");
    setDetail(payload.saved_count ? `(${payload.saved_count})` : "");
  }, []);

  const sendPlacementContext = useCallback(async () => {
    const viewportCenter = getViewportCenter(appStateRef.current);
    const payload = {
      pointer: pointerRef.current,
      viewport_center: viewportCenter,
    };
    if (!payload.pointer && !payload.viewport_center) {
      return;
    }
    const response = await fetch("/placement-context", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || `placement context failed: ${response.status}`);
    }
  }, []);

  const schedulePlacementContext = useCallback(
    (appState) => {
      if (appState) {
        appStateRef.current = appState;
      }
      window.clearTimeout(placementTimerRef.current);
      placementTimerRef.current = window.setTimeout(() => {
        sendPlacementContext().catch((error) => console.error(error));
      }, PLACEMENT_CONTEXT_DEBOUNCE_MS);
    },
    [sendPlacementContext],
  );

  const handleChange = useCallback(
    (elements, appState) => {
      schedulePlacementContext(appState);
      if (!hasMountedSceneRef.current || applyingRemoteRef.current) {
        return;
      }
      const nextSignature = layoutSignature(elements);
      if (nextSignature === lastLayoutSignatureRef.current) {
        return;
      }
      lastLayoutSignatureRef.current = nextSignature;
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = window.setTimeout(() => {
        saveLayout(elements).catch((error) => {
          console.error(error);
          setStatus("error");
          setDetail(error.message);
        });
      }, SAVE_DEBOUNCE_MS);
    },
    [saveLayout, schedulePlacementContext],
  );

  const handlePointerUpdate = useCallback(
    (payload) => {
      pointerRef.current = payload?.pointer || null;
      const currentAppState = api?.getAppState ? api.getAppState() : null;
      schedulePlacementContext(currentAppState);
    },
    [api, schedulePlacementContext],
  );

  const handleCanvasPointer = useCallback(
    (event) => {
      const currentAppState = api?.getAppState
        ? api.getAppState()
        : appStateRef.current;
      pointerRef.current = getScenePoint(
        event.clientX,
        event.clientY,
        currentAppState,
      );
      schedulePlacementContext(currentAppState);
    },
    [api, schedulePlacementContext],
  );

  const handleScrollChange = useCallback(() => {
    const currentAppState = api?.getAppState ? api.getAppState() : null;
    schedulePlacementContext(currentAppState);
  }, [api, schedulePlacementContext]);

  const handleCanvasWheel = useCallback(
    (event) => {
      if (
        !(event.target instanceof HTMLCanvasElement)
        || event.shiftKey
        || event.ctrlKey
        || event.metaKey
        || event.altKey
        || !api?.getAppState
      ) {
        return;
      }

      const appState = api.getAppState();
      const delta = normalizeWheelDelta(event, appState.height);
      if (!Number.isFinite(delta) || delta === 0) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      const currentZoom = appState.zoom?.value || 1;
      const nextZoom = clamp(
        currentZoom * Math.exp(-delta * WHEEL_ZOOM_SPEED),
        MIN_ZOOM,
        MAX_ZOOM,
      );
      if (nextZoom === currentZoom) {
        return;
      }

      const viewportX = event.clientX - (appState.offsetLeft || 0);
      const viewportY = event.clientY - (appState.offsetTop || 0);
      const sceneX = viewportX / currentZoom - (appState.scrollX || 0);
      const sceneY = viewportY / currentZoom - (appState.scrollY || 0);

      api.updateScene({
        appState: {
          zoom: { value: nextZoom },
          scrollX: viewportX / nextZoom - sceneX,
          scrollY: viewportY / nextZoom - sceneY,
        },
      });
    },
    [api],
  );

  useEffect(() => {
    return () => {
      window.clearTimeout(saveTimerRef.current);
      window.clearTimeout(placementTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!scene) {
      return;
    }
    const timer = window.setTimeout(() => {
      hasMountedSceneRef.current = true;
    }, 300);
    return () => window.clearTimeout(timer);
  }, [scene]);

  if (!scene) {
    return React.createElement(
      "div",
      { className: "viewer-shell" },
      React.createElement(Status, { status, detail }),
      React.createElement("div", { className: "loading-screen" }, "Loading diagram"),
    );
  }

  return React.createElement(
    "div",
    { className: "viewer-shell" },
    React.createElement(Status, { status, detail }),
    React.createElement(
      "div",
      {
        className: "viewer-canvas",
        onPointerDown: handleCanvasPointer,
        onPointerMove: handleCanvasPointer,
        onWheelCapture: handleCanvasWheel,
      },
      React.createElement(Excalidraw, {
        initialData: scene,
        excalidrawAPI: setApi,
        onChange: handleChange,
        onPointerUpdate: handlePointerUpdate,
        onScrollChange: handleScrollChange,
        autoFocus: true,
        theme: "light",
        UIOptions: {
          canvasActions: {
            loadScene: false,
          },
        },
      }),
    ),
  );
}

function getViewportCenter(appState) {
  if (!appState) {
    return null;
  }
  const zoom = appState.zoom?.value || 1;
  const width = appState.width || window.innerWidth;
  const height = appState.height || window.innerHeight;
  const offsetLeft = appState.offsetLeft || 0;
  const offsetTop = appState.offsetTop || 0;
  const scrollX = appState.scrollX || 0;
  const scrollY = appState.scrollY || 0;
  return {
    x: (width / 2 - offsetLeft) / zoom - scrollX,
    y: (height / 2 - offsetTop) / zoom - scrollY,
  };
}

function getScenePoint(clientX, clientY, appState) {
  if (!appState || !Number.isFinite(clientX) || !Number.isFinite(clientY)) {
    return null;
  }
  const zoom = appState.zoom?.value || 1;
  const offsetLeft = appState.offsetLeft || 0;
  const offsetTop = appState.offsetTop || 0;
  const scrollX = appState.scrollX || 0;
  const scrollY = appState.scrollY || 0;
  return {
    x: (clientX - offsetLeft) / zoom - scrollX,
    y: (clientY - offsetTop) / zoom - scrollY,
  };
}

function normalizeWheelDelta(event, viewportHeight) {
  let delta = event.deltaY;
  if (event.deltaMode === WheelEvent.DOM_DELTA_LINE) {
    delta *= 16;
  } else if (event.deltaMode === WheelEvent.DOM_DELTA_PAGE) {
    delta *= viewportHeight || window.innerHeight;
  }
  return clamp(delta, -MAX_WHEEL_ZOOM_DELTA, MAX_WHEEL_ZOOM_DELTA);
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function layoutSignature(elements) {
  return JSON.stringify(
    (elements || [])
      .filter((element) => element.customData?.node_id)
      .map((element) => ({
        id: element.id,
        nodeId: element.customData.node_id,
        type: element.type,
        isDeleted: Boolean(element.isDeleted),
        x: element.x,
        y: element.y,
        width: element.width,
        height: element.height,
        textAlign: element.textAlign,
        verticalAlign: element.verticalAlign,
        fontSize: element.fontSize,
        text: element.type === "text" ? element.text : undefined,
        originalText: element.type === "text" ? element.originalText : undefined,
      })),
  );
}

function Status({ status, detail }) {
  return React.createElement(
    "div",
    {
      className: "status-pill",
      "data-state": status,
      title: statusLabel(status, detail),
    },
    React.createElement("span", { className: "status-text" }, status),
    detail
      ? React.createElement("span", { className: "status-detail" }, detail)
      : null,
  );
}

const root = createRoot(document.getElementById("root"));
root.render(React.createElement(App));
