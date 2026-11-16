import {
  Cpu,
  Monitor,
  Network,
  Router,
  ScanLine,
  Server,
  Shield,
  Wifi,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '@/lib/utils'

const TYPE_ICONS: Record<string, LucideIcon> = {
  firewall: Shield,
  switch: Network,
  server: Server,
  plc: Cpu,
  hmi: Monitor,
  ap: Wifi,
  scanner: ScanLine,
}

export function deviceTypeIcon(type: string): LucideIcon {
  return TYPE_ICONS[type.toLowerCase()] ?? Router
}

export default function DeviceTypeIcon({
  type,
  className,
}: {
  type: string
  className?: string
}) {
  const Icon = deviceTypeIcon(type)
  return <Icon className={cn('h-4 w-4', className)} />
}
