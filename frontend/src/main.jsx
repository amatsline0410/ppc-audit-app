import React, { Suspense, lazy } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

// Storefront-first routing:
//   /            -> FamiliaOps storefront (public marketing page)
//   /familiaops  -> same page (kept as an alias)
//   anything else (/login, /<store>/<tab>...) -> the console app
// FamiliaOps is lazy so its stylesheet is code-split and never loads inside the app.
const FamiliaOps = lazy(() => import('./familia/FamiliaOps.jsx'))
const path = window.location.pathname.replace(/\/+$/, '') || '/'
const isStorefront = path === '/' || path === '/familiaops'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {isStorefront
      ? <Suspense fallback={null}><FamiliaOps /></Suspense>
      : <App />}
  </React.StrictMode>
)
