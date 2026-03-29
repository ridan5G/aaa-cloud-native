export type ProfileStatus    = 'active' | 'suspended' | 'terminated'
export type JobStatus        = 'queued' | 'running' | 'completed' | 'failed'
export type IpResolution     = 'imsi' | 'imsi_apn' | 'iccid' | 'iccid_apn'
export type ProvisioningMode = 'first_connect' | 'immediate'

export interface ApnIp {
  id?:       number
  apn:       string | null
  static_ip: string | null
  pool_id:   string | null
  pool_name?: string
}

export interface IccidIp {
  id?:       number
  apn:       string | null
  static_ip: string | null
  pool_id:   string | null
  pool_name?: string
}

export interface Imsi {
  imsi:     string
  status:   'active' | 'suspended'
  priority: number
  apn_ips:  ApnIp[]
}

export interface Profile {
  sim_id:        string
  iccid:         string | null
  account_name:  string | null
  status:        ProfileStatus
  ip_resolution: IpResolution
  metadata?:     { imei?: string; tags?: string[] }
  imsis?:        Imsi[]
  iccid_ips?:    IccidIp[]
  created_at:    string
  updated_at:    string
}

export interface RoutingDomain {
  id:               string
  name:             string
  description:      string | null
  allowed_prefixes: string[]
  pool_count?:      number
  created_at?:      string
  updated_at?:      string
}

export interface SuggestCidrResult {
  suggested_cidr:      string
  prefix_len:          number
  usable_hosts:        number
  routing_domain_id:   string
  routing_domain_name: string
}

export interface Pool {
  pool_id:           string
  name:              string
  account_name:      string | null
  routing_domain:    string        // domain name (denormalized for display)
  routing_domain_id: string        // domain UUID
  subnet:            string
  start_ip:          string
  end_ip:            string
  status:            'active' | 'suspended'
}

export interface PoolStats {
  total:     number
  allocated: number
  available: number
}

export interface RangeConfig {
  id:               number
  account_name:     string | null
  f_imsi:           string
  t_imsi:           string
  pool_id:          string | null
  pool_name?:       string
  ip_resolution:    IpResolution
  description:      string | null
  status:           'active' | 'suspended'
  iccid_range_id:   number | null
  provisioning_mode: ProvisioningMode
}

export interface ApnPool {
  id:        number
  apn:       string
  pool_id:   string
  pool_name?: string
}

export interface IccidRangeConfig {
  id:               number
  account_name:     string | null
  f_iccid:          string
  t_iccid:          string
  pool_id:          string | null
  pool_name?:       string
  ip_resolution:    IpResolution
  imsi_count:       number
  description:      string | null
  status:           'active' | 'suspended'
  imsi_ranges?:     ImsiSlot[]
  provisioning_mode: ProvisioningMode
}

export interface ImsiSlot {
  id:            number
  imsi_slot:     number
  f_imsi:        string
  t_imsi:        string
  pool_id:       string | null
  pool_name?:    string
  ip_resolution: IpResolution
  description:   string | null
}

export interface BulkJob {
  job_id:     string
  status:     JobStatus
  submitted:  number
  processed:  number
  failed:     number
  created_at: string
  errors?:    Array<{ row: number; field: string; message: string; value: string }>
}
