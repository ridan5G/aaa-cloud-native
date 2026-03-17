import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Devices from './pages/Subscribers'
import Pools from './pages/Pools'
import RangeConfigs from './pages/RangeConfigs'
import IccidRangeConfigs from './pages/IccidRangeConfigs'
import BulkJobs from './pages/BulkJobs'
import SimProfileTypes from './pages/SimProfileTypes'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard"             element={<Dashboard />} />
        <Route path="devices/*"              element={<Devices />} />
        <Route path="pools/*"               element={<Pools />} />
        <Route path="range-configs/*"       element={<RangeConfigs />} />
        <Route path="iccid-range-configs/*" element={<IccidRangeConfigs />} />
        <Route path="bulk-jobs/*"           element={<BulkJobs />} />
        <Route path="sim-profile-types"     element={<SimProfileTypes />} />
      </Route>
    </Routes>
  )
}
