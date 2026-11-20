import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Paper Hunt",
  description: "每日追踪 Agent 演化、Agent 记忆、电商交互导购和多模态 Agent 研究，提供中文摘要与入选依据。"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

