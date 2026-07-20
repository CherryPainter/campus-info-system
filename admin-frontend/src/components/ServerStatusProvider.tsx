/**
 * 服务器状态全局提供者
 * 统一处理服务器离线检测和提示
 */
import { useState, useEffect, createContext, useContext } from "react";
import { DisconnectOutlined, LoadingOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { useIntervalPolling } from "@/hooks/useIntervalPolling";
import { POLL_FAST } from "@/hooks/pollIntervals";

interface ServerStatusContextType {
  isOffline: boolean;
  setIsOffline: (offline: boolean) => void;
}

const ServerStatusContext = createContext<ServerStatusContextType>({
  isOffline: false,
  setIsOffline: () => {},
});

export const useServerStatus = () => useContext(ServerStatusContext);

async function checkServerAlive(): Promise<boolean> {
  try {
    const resp = await fetch("/api/ping", {
      method: "GET",
      cache: "no-cache",
      credentials: "omit",
    });
    return resp.ok;
  } catch {
    return false;
  }
}

export function ServerStatusProvider({ children }: { children: React.ReactNode }) {
  const [isOffline, setIsOffline] = useState(false);

  useEffect(() => {
    const handleOffline = () => setIsOffline(true);
    const handleOnline = () => setIsOffline(false);

    window.addEventListener("server-offline", handleOffline);
    window.addEventListener("server-online", handleOnline);

    return () => {
      window.removeEventListener("server-offline", handleOffline);
      window.removeEventListener("server-online", handleOnline);
    };
  }, []);

  // 离线时每 2 秒探测一次服务器存活（统一轮询 Hook，仅 isOffline 时启用）
  // immediate=false：刚离线时延迟一个周期再首探，避免与离线判定瞬间抖动
  useIntervalPolling(
    async () => {
      const isAlive = await checkServerAlive();
      if (isAlive) {
        setIsOffline(false);
        window.dispatchEvent(new CustomEvent("server-online"));
      }
    },
    POLL_FAST,
    isOffline,
    false
  );

  if (isOffline) {
    return (
      <div
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: "#fff2f0",
          zIndex: 9999,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          transition: "background 0.3s ease",
        }}
      >
        <DisconnectOutlined style={{ fontSize: 80, color: "#ff4d4f", marginBottom: 24 }} />
        <div style={{ fontSize: 28, fontWeight: "bold", color: "#ff4d4f", marginBottom: 16 }}>
          服务器离线
        </div>
        <div style={{ fontSize: 16, color: "#666", marginBottom: 32 }}>
          无法连接到后端服务器，请检查服务是否正常运行
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#999" }}>
          <LoadingOutlined spin style={{ fontSize: 20 }} />
          <span>自动检测服务器中...</span>
        </div>
      </div>
    );
  }

  return (
    <ServerStatusContext.Provider value={{ isOffline, setIsOffline }}>
      {children}
    </ServerStatusContext.Provider>
  );
}
