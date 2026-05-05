import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Excalidraw } from "https://esm.sh/@excalidraw/excalidraw@0.18.0/dist/dev/index.js?external=react,react-dom";

const SAVE_DEBOUNCE_MS = 800;

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

  const handleChange = useCallback(
    (elements) => {
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
    [saveLayout],
  );

  useEffect(() => {
    return () => window.clearTimeout(saveTimerRef.current);
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
      { className: "viewer-canvas" },
      React.createElement(Excalidraw, {
        initialData: scene,
        excalidrawAPI: setApi,
        onChange: handleChange,
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
