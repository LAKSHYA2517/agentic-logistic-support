import React, { useState, useEffect, useCallback } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { Dashboard } from './components/Dashboard';
import { INITIAL_MOCK_SHIPMENTS } from './utils/constants';

function App() {
  const [shipments, setShipments] = useState(() => {
    try {
      const saved = localStorage.getItem('sauda_shipments');
      if (saved) return JSON.parse(saved);
    } catch (e) {
      console.warn('Could not read from localStorage', e);
    }
    return INITIAL_MOCK_SHIPMENTS;
  });

  const [lang, setLang] = useState(() => {
    try {
      return localStorage.getItem('sauda_lang') || 'en';
    } catch (e) {
      return 'en';
    }
  });

  const [darkMode, setDarkMode] = useState(() => {
    try {
      const savedTheme = localStorage.getItem('sauda_theme');
      return savedTheme === 'dark';
    } catch (e) {
      return false;
    }
  });

  const [highlightedIds, setHighlightedIds] = useState(new Set());

  // Sync shipments to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('sauda_shipments', JSON.stringify(shipments));
    } catch (e) {
      console.warn('Could not save to localStorage', e);
    }
  }, [shipments]);

  // Sync theme to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('sauda_theme', darkMode ? 'dark' : 'light');
    } catch (e) {
      // ignore
    }
  }, [darkMode]);

  // Sync language to localStorage
  const handleSetLang = useCallback((newLang) => {
    setLang(newLang);
    try {
      localStorage.setItem('sauda_lang', newLang);
    } catch (e) {
      // ignore
    }
  }, []);

  // Flash / Highlight newly updated or added rows (soft 1.2s fade)
  const triggerHighlight = useCallback((id) => {
    setHighlightedIds((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });

    setTimeout(() => {
      setHighlightedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, 1200);
  }, []);

  // Clear all data from state and localStorage
  const handleClearAllData = useCallback(() => {
    setShipments([]);
    setHighlightedIds(new Set());
    try {
      localStorage.removeItem('sauda_shipments');
    } catch (e) {
      // ignore
    }
  }, []);

  // Process incoming WebSocket or Simulated payloads
  const handleIncomingPayload = useCallback((payload) => {
    if (!payload) return;

    const shipmentData = payload.data || payload;

    if (!shipmentData || !shipmentData.id) {
      console.warn('Invalid shipment payload received:', payload);
      return;
    }

    const normalizedShipment = {
      ...shipmentData,
      advance_paid: Number(shipmentData.advance_paid) || 0,
      balance_due: Number(shipmentData.balance_due) || 0,
      updated_at: shipmentData.updated_at || new Date().toISOString(),
    };

    setShipments((prevShipments) => {
      const existsIndex = prevShipments.findIndex((s) => s.id === normalizedShipment.id);

      if (existsIndex >= 0) {
        // Update existing shipment in-place
        const updated = [...prevShipments];
        updated[existsIndex] = {
          ...updated[existsIndex],
          ...normalizedShipment,
        };
        return updated;
      } else {
        // Prepend new shipment to the top of ledger
        return [normalizedShipment, ...prevShipments];
      }
    });

    triggerHighlight(normalizedShipment.id);
  }, [triggerHighlight]);

  // WebSocket hook with auto reconnection & native browser WebSocket
  const {
    status: wsStatus,
    url: wsUrl,
    setUrl: setWsUrl,
    connect: wsConnect,
    disconnect: wsDisconnect,
    injectLocalPayload,
    logs: wsLogs,
    clearLogs: clearWsLogs,
  } = useWebSocket({
    defaultUrl: 'ws://localhost:8000/ws',
    onMessageReceived: handleIncomingPayload,
    autoConnect: true,
  });

  // Manual status transition from UI (e.g. In Transit -> Delivered)
  const handleStatusChange = useCallback((id, newStatus) => {
    setShipments((prev) =>
      prev.map((item) => {
        if (item.id === id) {
          const updated = {
            ...item,
            status: newStatus,
            updated_at: new Date().toISOString(),
          };
          triggerHighlight(id);
          return updated;
        }
        return item;
      })
    );
  }, [triggerHighlight]);

  // Push mock voice payload through WebSocket handler
  const handleSimulateVoicePayload = useCallback((payload) => {
    injectLocalPayload(payload);
  }, [injectLocalPayload]);

  return (
    <Dashboard
      shipments={shipments}
      highlightedIds={highlightedIds}
      wsStatus={wsStatus}
      wsUrl={wsUrl}
      onUpdateWsUrl={setWsUrl}
      onConnect={wsConnect}
      onDisconnect={wsDisconnect}
      wsLogs={wsLogs}
      onClearWsLogs={clearWsLogs}
      onSimulateVoicePayload={handleSimulateVoicePayload}
      onClearAllData={handleClearAllData}
      onStatusChange={handleStatusChange}
      lang={lang}
      setLang={handleSetLang}
      darkMode={darkMode}
      setDarkMode={setDarkMode}
    />
  );
}

export default App;
