import type { DashboardSnapshot } from "./types";

export type WebSocketMessageHandler = (payload: unknown) => void;

export class DashboardSocket {
  private socket: WebSocket | null = null;

  constructor(private readonly url: string) {}

  connect(onMessage: WebSocketMessageHandler): void {
    if (typeof window === "undefined") {
      return;
    }
    this.socket = new WebSocket(this.url);
    this.socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data) as DashboardSnapshot);
      } catch {
        onMessage(event.data);
      }
    };
  }

  disconnect(): void {
    this.socket?.close();
    this.socket = null;
  }
}

