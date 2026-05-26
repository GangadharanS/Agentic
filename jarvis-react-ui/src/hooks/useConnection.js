import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';

export function useConnection() {
  const [isConnected, setIsConnected] = useState(false);
  const [tools, setTools] = useState([]);
  const [loading, setLoading] = useState(true);

  const checkConnection = useCallback(async () => {
    try {
      const health = await api.checkHealth();
      setIsConnected(health.status === 'connected');
      
      if (health.status === 'connected') {
        const toolsData = await api.getTools();
        setTools(toolsData.tools || []);
      }
    } catch (error) {
      setIsConnected(false);
      setTools([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkConnection();
    const interval = setInterval(checkConnection, 30000);
    return () => clearInterval(interval);
  }, [checkConnection]);

  return { isConnected, tools, loading, refresh: checkConnection };
}

export default useConnection;
