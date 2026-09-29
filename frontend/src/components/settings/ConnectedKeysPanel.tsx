import React from 'react'
import type { ProviderDefinition } from '../../types/provider'
import { ProviderIcon } from '../providers/ProviderIcon'


export function ConnectedKeysPanel({
  selectedProvider,
  connectionsCount,
  keysCount,
  children,
}: {
  selectedProvider?: ProviderDefinition
  connectionsCount: number
  keysCount: number
  children: React.ReactNode
}) {
  const title = selectedProvider?.name ?? 'Connected API Keys'

  return (
    <div className="flex h-full flex-col min-h-0">
      {/* Header without rigid box border - clean, modern, spacious */}
      <div className="flex items-center justify-between border-b border-line/50 pb-3 mb-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5">
            {selectedProvider && (
              <div className="flex size-8 shrink-0 items-center justify-center rounded-xl border border-line/60 bg-panel2 p-1.5 shadow-2xs">
                <ProviderIcon
                  providerId={selectedProvider.id}
                  name={selectedProvider.name}
                  className="size-5"
                  decorative
                />
              </div>
            )}
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="truncate text-base font-bold text-fg">{title}</h2>
                {selectedProvider && (
                  <span className="font-mono text-xs text-muted">({selectedProvider.id})</span>
                )}
              </div>
              <p className="text-xs text-muted">
                {connectionsCount} connection{connectionsCount === 1 ? '' : 's'} · {keysCount} active key{keysCount === 1 ? '' : 's'}
              </p>
            </div>
          </div>
        </div>

        {/* Header content only - no duplicate Add connection button */}
      </div>

      {/* Body containing Connection Cards & Model List */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-0.5">
        {children}
      </div>
    </div>
  )
}
