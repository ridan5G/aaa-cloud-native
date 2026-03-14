import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Subscribers from './pages/Subscribers'
import Pools from './pages/Pools'
import RangeConfigs from './pages/RangeConfigs'
import BulkJobs from './pages/BulkJobs'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="subscribers/*" element={<Subscribers />} />
        <Route path="pools/*" element={<Pools />} />
        <Route path="range-configs/*" element={<RangeConfigs />} />
        <Route path="bulk-jobs/*" element={<BulkJobs />} />
      </Route>
    </Routes>
  )
}
