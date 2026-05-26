import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { GlobalHomeDock } from "../components/navigation/GlobalHomeDock";

export const metadata: Metadata = {
  title: "Scalping System",
  description: "Real-time scalping operating console",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="appFrame">
          <GlobalHomeDock />
          <div className="appContent">{children}</div>
        </div>
      </body>
    </html>
  );
}
