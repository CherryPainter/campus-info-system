/**
 * 应用渲染入口
 * 使用 React 18 的 createRoot API
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./style.css";

// 获取根节点
const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("未找到 root 元素");
}

// 创建 React 根节点并渲染
createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>
);
