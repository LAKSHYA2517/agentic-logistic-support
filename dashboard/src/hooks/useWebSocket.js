import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * Native WebSocket hook with auto-reconnect backoff and local event dispatch capabilities.
 */
export function useWebSocket({
  defaultUrl = 'ws://localhost:8000/ws',
  onMessageReceived,
  autoConnect = true,
  maxReconnectAttempts = 10,
  initialReconnectDelayMs = 1500,
} = {}) {
  const [url, setUrl] = useState(defaultUrl);
  const [status, setStatus] = useState('disconnected'); // 'connected' | 'connecting' | 'reconnecting' | 'disconnected'
  const [lastMessage, setLastMessage] = useState(null);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [logs, setLogs] = useState([]);

  const socketRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const isManuallyClosedRef = useRef(false);
  const onMessageCallbackRef = useRef(onMessageReceived);

  useEffect(() => {
    onMessageCallbackRef.current = onMessageReceived;
  }, [onMessageReceived]);

  const addLog = useCallback((type, text, payload = null) => {
    setLogs((prev) => [
      {
        id: Math.random().toString(36).substring(2, 9),
        timestamp: new Date().toISOString(),
        type, // 'info' | 'success' | 'warn' | 'error' | 'ws_in' | 'ws_out'
        text,
        payload,
      },
      ...prev.slice(0, 49), // Keep latest 50 logs
    ]);
  }, []);

  const connect = useCallback((targetUrl = url) => {
    if (socketRef.current) {
      try {
        socketRef.current.close();
      } catch (e) {
        // ignore
      }
    }

    isManuallyClosedRef.current = false;
    setStatus((prev) => (reconnectAttempts > 0 ? 'reconnecting' : 'connecting'));
    addLog('info', `Attempting WebSocket connection to ${targetUrl}...`);

    try {
      const ws = new WebSocket(targetUrl);
      socketRef.current = ws;

      ws.onopen = () => {
        setStatus('connected');
        setReconnectAttempts(0);
        addLog('success', `WebSocket connected to ${targetUrl}`);
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          setLastMessage(parsed);
          addLog('ws_in', `Received ${parsed.event || 'message'}`, parsed);
          if (onMessageCallbackRef.current) {
            onMessageCallbackRef.current(parsed);
          }
        } catch (err) {
          const raw = { raw: event.data };
          setLastMessage(raw);
          addLog('ws_in', 'Received raw text payload', raw);
          if (onMessageCallbackRef.current) {
            onMessageCallbackRef.current(raw);
          }
        }
      };

      ws.onerror = (err) => {
        addLog('warn', `WebSocket connection error on ${targetUrl}`);
      };

      ws.onclose = (event) => {
        socketRef.current = null;
        if (isManuallyClosedRef.current) {
          setStatus('disconnected');
          addLog('info', 'WebSocket closed intentionally');
          return;
        }

        setStatus('disconnected');
        addLog('warn', `WebSocket closed (code: ${event.code}). Retrying in background...`);

        // Exponential backoff
        setReconnectAttempts((prev) => {
          const nextAttempt = prev + 1;
          if (nextAttempt <= maxReconnectAttempts) {
            const delay = Math.min(initialReconnectDelayMs * Math.pow(1.5, prev), 15000);
            setStatus('reconnecting');
            if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = setTimeout(() => {
              connect(targetUrl);
            }, delay);
          } else {
            addLog('error', `Max reconnection attempts (${maxReconnectAttempts}) reached.`);
          }
          return nextAttempt;
        });
      };
    } catch (error) {
      setStatus('disconnected');
      addLog('error', `Failed to initialize WebSocket: ${error.message}`);
    }
  }, [url, reconnectAttempts, maxReconnectAttempts, initialReconnectDelayMs, addLog]);

  const disconnect = useCallback(() => {
    isManuallyClosedRef.current = true;
    if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
    setStatus('disconnected');
  }, []);

  const sendMessage = useCallback((data) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      const payload = typeof data === 'string' ? data : JSON.stringify(data);
      socketRef.current.send(payload);
      addLog('ws_out', 'Sent message to server', data);
      return true;
    } else {
      addLog('warn', 'Cannot send message: WebSocket is not open');
      return false;
    }
  }, [addLog]);

  // Direct injection for simulation / testing
  const injectLocalPayload = useCallback((payload) => {
    setLastMessage(payload);
    addLog('ws_in', `[SIMULATED WS] ${payload.event || 'EVENT'}`, payload);
    if (onMessageCallbackRef.current) {
      onMessageCallbackRef.current(payload);
    }
  }, [addLog]);

  useEffect(() => {
    if (autoConnect) {
      connect(url);
    }
    return () => {
      isManuallyClosedRef.current = true;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (socketRef.current) socketRef.current.close();
    };
  }, [url, autoConnect]);

  return {
    status,
    url,
    setUrl,
    connect,
    disconnect,
    sendMessage,
    injectLocalPayload,
    lastMessage,
    reconnectAttempts,
    logs,
    clearLogs: () => setLogs([]),
  };
}
