import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { PlatformTheme } from './components/ui/PlatformTheme';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <PlatformTheme><App /></PlatformTheme>
  </React.StrictMode>,
);
