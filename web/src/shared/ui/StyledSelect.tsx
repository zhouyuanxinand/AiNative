import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

export interface StyledSelectOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
  title?: string;
}

interface StyledSelectProps {
  id?: string;
  name?: string;
  value: string;
  options: StyledSelectOption[];
  onChange: (value: string) => void;
  className?: string;
  placeholder?: ReactNode;
  disabled?: boolean;
  required?: boolean;
  invalid?: boolean;
  'aria-label'?: string;
  'aria-labelledby'?: string;
}

interface PortalPosition {
  placement: 'top' | 'bottom';
  style: CSSProperties;
}

export function StyledSelect({
  id,
  name,
  value,
  options,
  onChange,
  className = '',
  placeholder = '请选择',
  disabled = false,
  required = false,
  invalid = false,
  'aria-label': ariaLabel,
  'aria-labelledby': ariaLabelledby,
}: StyledSelectProps) {
  const generatedId = useId().replaceAll(':', '');
  const controlId = id || `styled-select-${generatedId}`;
  const nativeId = `${controlId}-native`;
  const valueId = `${controlId}-value`;
  const menuId = `${controlId}-menu`;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [portalHost, setPortalHost] = useState<HTMLDialogElement | null>(null);
  const [portalPosition, setPortalPosition] = useState<PortalPosition | null>(null);

  const selected = options.find((option) => option.value === value);

  useLayoutEffect(() => {
    setPortalHost(rootRef.current?.closest('dialog') ?? null);
  }, []);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, []);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const positionPortalMenu = useCallback(() => {
    if (!portalHost || !triggerRef.current) return;
    const triggerRect = triggerRef.current.getBoundingClientRect();
    const dialogRect = portalHost.getBoundingClientRect();
    const gap = 7;
    const inset = 8;
    const topLimit = Math.max(inset, dialogRect.top + inset);
    const bottomLimit = Math.min(window.innerHeight - inset, dialogRect.bottom - inset);
    const leftLimit = Math.max(inset, dialogRect.left + inset);
    const rightLimit = Math.min(window.innerWidth - inset, dialogRect.right - inset);
    const spaceBelow = Math.max(0, bottomLimit - triggerRect.bottom - gap);
    const spaceAbove = Math.max(0, triggerRect.top - topLimit - gap);
    const placement = spaceBelow < 180 && spaceAbove > spaceBelow ? 'top' : 'bottom';
    const availableHeight = Math.floor(placement === 'top' ? spaceAbove : spaceBelow);
    const width = Math.max(0, Math.min(triggerRect.width, rightLimit - leftLimit));
    const left = Math.min(Math.max(triggerRect.left, leftLimit), Math.max(leftLimit, rightLimit - width));

    setPortalPosition({
      placement,
      style: {
        position: 'fixed',
        left,
        right: 'auto',
        top: placement === 'bottom' ? triggerRect.bottom + gap : 'auto',
        bottom: placement === 'top' ? window.innerHeight - triggerRect.top + gap : 'auto',
        width,
        maxHeight: availableHeight,
        boxSizing: 'border-box',
        opacity: 1,
        transform: 'none',
        pointerEvents: 'auto',
      },
    });
  }, [portalHost]);

  useLayoutEffect(() => {
    if (!open || !portalHost) {
      setPortalPosition(null);
      return;
    }
    positionPortalMenu();
    const reposition = () => positionPortalMenu();
    window.addEventListener('resize', reposition);
    document.addEventListener('scroll', reposition, true);
    return () => {
      window.removeEventListener('resize', reposition);
      document.removeEventListener('scroll', reposition, true);
    };
  }, [open, portalHost, positionPortalMenu]);

  const choose = (option: StyledSelectOption) => {
    if (disabled || option.disabled) return;
    onChange(option.value);
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const moveToOption = (direction: 1 | -1) => {
    const enabledOptions = options.filter((option) => !option.disabled);
    if (enabledOptions.length === 0) return;
    const currentIndex = Math.max(
      0,
      enabledOptions.findIndex((option) => option.value === value),
    );
    const nextIndex = (currentIndex + direction + enabledOptions.length) % enabledOptions.length;
    choose(enabledOptions[nextIndex]);
  };

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
      event.preventDefault();
      if (!open) setOpen(true);
      else moveToOption(1);
      return;
    }
    if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
      event.preventDefault();
      if (!open) setOpen(true);
      else moveToOption(-1);
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      setOpen((current) => !current);
    }
  };

  const closeFromEscape = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Escape' || !open) return;
    event.preventDefault();
    event.stopPropagation();
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const menu = (
    <div
      ref={menuRef}
      className={`select-menu ${portalHost ? 'select-menu-portal' : ''}`}
      id={menuId}
      role="listbox"
      aria-hidden={!open}
      data-placement={portalPosition?.placement}
      style={portalHost ? portalPosition?.style : undefined}
      onKeyDown={closeFromEscape}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="select-option"
          role="option"
          aria-selected={option.value === value}
          disabled={option.disabled}
          title={option.title}
          tabIndex={open && !option.disabled ? 0 : -1}
          onClick={() => choose(option)}
        >
          <span>{option.label}</span>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="m5 12 4 4L19 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      ))}
    </div>
  );

  return (
    <>
      <div
        ref={rootRef}
        className={`select-control ${open ? 'open' : ''} ${disabled ? 'disabled' : ''} ${invalid ? 'invalid-field' : ''} ${className}`.trim()}
        onKeyDown={closeFromEscape}
      >
        <select
          id={nativeId}
          name={name}
          value={value}
          required={required}
          disabled={disabled}
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => onChange(event.target.value)}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled} title={option.title}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          id={controlId}
          ref={triggerRef}
          type="button"
          className={`select-trigger ${selected ? 'has-value' : ''}`}
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledby ? `${ariaLabelledby} ${valueId}` : undefined}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={menuId}
          aria-invalid={invalid}
          disabled={disabled}
          title={selected?.title ?? (typeof selected?.label === 'string' ? selected.label : undefined)}
          onClick={() => setOpen((current) => !current)}
          onKeyDown={onTriggerKeyDown}
        >
          <span id={valueId}>{selected?.label ?? placeholder}</span>
          <svg className="select-chevron" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="m7 10 5 5 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {!portalHost && menu}
      </div>
      {portalHost && open && portalPosition && createPortal(menu, portalHost)}
    </>
  );
}
