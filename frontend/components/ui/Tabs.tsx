'use client';

export function Tabs({ items, active, onChange }: TabsProps) {
  return (
    <div role="tablist" className="flex items-center gap-2 border-b border-border">
      {items.map((item) => {
        const isActive = item.id === active;
        return (
          <button
            key={item.id}
            role="tab"
            aria-selected={isActive}
            className={`-mb-px min-h-11 border-b-2 px-3 py-2 text-sm transition-colors ${
              isActive
                ? 'border-primary font-medium text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => onChange(item.id)}
            type="button"
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

export interface TabItem {
  id: string;
  label: string;
}

interface TabsProps {
  items: TabItem[];
  active: string;
  onChange: (id: string) => void;
}
