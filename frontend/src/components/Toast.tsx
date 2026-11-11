import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';
import clsx from 'clsx';

type ToastType = 'success' | 'error' | 'info';
interface ToastItem { id: number; message: string; type: ToastType }

interface ToastCtx {
  toast: (msg: string, type?: ToastType) => void;
}
const Ctx = createContext<ToastCtx>({ toast: () => {} });
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, type: ToastType = 'info') => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, message, type }]);
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 3500);
  }, []);

  return (
    <Ctx.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            className={clsx(
              'flex items-center gap-3 min-w-[280px] max-w-sm rounded-lg border px-4 py-3 shadow-pop animate-fade-up',
              t.type === 'success' && 'border-brand-200 bg-white text-ink',
              t.type === 'error' && 'border-red-200 bg-white text-red-600',
              t.type === 'info' && 'border-edge bg-white text-sub'
            )}
          >
            {t.type === 'success' && <CheckCircle2 size={17} className="text-brand-500" />}
            {t.type === 'error' && <AlertCircle size={17} className="text-red-500" />}
            {t.type === 'info' && <Info size={17} className="text-faint" />}
            <span className="text-[13px] flex-1">{t.message}</span>
            <button onClick={() => setItems((p) => p.filter((x) => x.id !== t.id))} className="text-faint hover:text-ink">
              <X size={15} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}