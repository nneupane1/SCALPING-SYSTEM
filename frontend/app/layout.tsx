import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { GlobalHomeDock } from "../components/navigation/GlobalHomeDock";

export const metadata: Metadata = {
  title: "QuantFund AI",
  description: "QuantFund AI research, replay, paper, and live trading cockpit",
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
