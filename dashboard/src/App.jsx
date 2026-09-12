import React, { useState, useEffect, useCallback } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { Dashboard } from './components/Dashboard';
import { INITIAL_MOCK_SHIPMENTS } from './utils/constants';

// How often to refetch real shipment state from the backend. The
// backend has no WebSocket/SSE push channel yet, so a short-interval
// refetch is the simplest way to reflect seller/driver WhatsApp
// activity without standing up new infrastructure (see useWebSocket,
// which stays wired to ws://localhost:8000/ws for the existing
// simulator/demo path and simply shows "disconnected" if nothing is
// listening there -- harmless).
const SHIPMENTS_POLL_INTERVAL_MS = 4000;

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

  // Poll the real backend for shipment state. The backend response is
  // the source of truth for every shipment it knows about: this
  // replaces the shipment list with exactly what it returns each
  // cycle, so a shipment cleared from the database (or otherwise no
  // longer returned) disappears from the dashboard too, instead of
  // lingering forever in local state / localStorage. Only rows that
  // actually changed get the highlight flash, and locally-simulated
  // demo shipments (Voice Simulator) are expected to be transient now
  // that a real backend is the source of truth -- they survive until
  // the next poll tick.
  const fetchShipmentsFromBackend = useCallback(async () => {
    let response;
    try {
      response = await fetch('/api/shipments');
    } catch (e) {
      return; // backend unreachable this cycle -- retry next interval
    }
    if (!response.ok) return;

    let backendShipments;
    try {
      backendShipments = await response.json();
    } catch (e) {
      return;
    }
    if (!Array.isArray(backendShipments)) return;

    const normalized = backendShipments
      .filter((raw) => raw && raw.id)
      .map((raw) => ({
        ...raw,
        advance_paid: Number(raw.advance_paid) || 0,
        balance_due: Number(raw.balance_due) || 0,
        updated_at: raw.updated_at || new Date().toISOString(),
      }));

    const changedIds = [];
    setShipments((prevShipments) => {
      const previousById = new Map(prevShipments.map((s) => [s.id, s]));
      for (const shipment of normalized) {
        const previous = previousById.get(shipment.id);
        const changed =
          !previous ||
          previous.status !== shipment.status ||
          previous.party_name !== shipment.party_name ||
          previous.truck_number !== shipment.truck_number ||
          previous.destination !== shipment.destination ||
          Number(previous.advance_paid) !== shipment.advance_paid ||
          Number(previous.balance_due) !== shipment.balance_due;
        if (changed) changedIds.push(shipment.id);
      }
      return normalized;
    });

    changedIds.forEach(triggerHighlight);
  }, [triggerHighlight]);

  useEffect(() => {
    fetchShipmentsFromBackend();
    const intervalId = setInterval(fetchShipmentsFromBackend, SHIPMENTS_POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchShipmentsFromBackend]);

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
