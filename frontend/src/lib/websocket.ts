"use client";

import { WSEvent } from "./api";
import { getAccessToken } from "./supabase";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

type Listener = (event: WSEvent) => void;

class SessionWebSocket {
  private ws: WebSocket | null = null;
  private listeners: Set<Listener> = new Set();
  private sessionId: string;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = true;

  constructor(sessionId: string) {
    this.sessionId = sessionId;
  }

  connect() {
    this.shouldReconnect = true;
    this._connect();
  }

  private _connect() {
    // The backend validates the Supabase token on connect (4401 = not signed in,
    // 4404 = not your session). Fetch a fresh token for every (re)connect.
    getAccessToken().then((token) => {
      if (!this.shouldReconnect) return;
      const url = token
        ? `${WS_BASE}/ws/${this.sessionId}?token=${encodeURIComponent(token)}`
        : `${WS_BASE}/ws/${this.sessionId}`;
      this._open(url);
    });
  }

  private _open(url: string) {
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WSEvent;
        this.listeners.forEach((fn) => fn(data));
      } catch {}
    };

    this.ws.onclose = (ev) => {
      // Auth rejections are permanent for this token — don't hammer the server.
      if (ev.code === 4401 || ev.code === 4404) return;
      if (this.shouldReconnect) {
        this.reconnectTimer = setTimeout(() => this._connect(), 3000);
      }
    };
  }

  subscribe(fn: Listener) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }
}

const _sockets: Map<string, SessionWebSocket> = new Map();

export function getSessionWS(sessionId: string): SessionWebSocket {
  if (!_sockets.has(sessionId)) {
    const ws = new SessionWebSocket(sessionId);
    ws.connect();
    _sockets.set(sessionId, ws);
  }
  return _sockets.get(sessionId)!;
}
