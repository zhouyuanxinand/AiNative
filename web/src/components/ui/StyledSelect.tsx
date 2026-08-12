import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react';

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
}: StyledSelectProps) {
  const generatedId = useId().replaceAll(':', '');
  const controlId = id || `styled-select-${generatedId}`;
  const menuId = `${controlId}-menu`;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);

  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, []);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

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
    if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
      return;
    }
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

  return (
    <div
      ref={rootRef}
      className={`select-control ${open ? 'open' : ''} ${disabled ? 'disabled' : ''} ${invalid ? 'invalid-field' : ''} ${className}`.trim()}
    >
      <select
        id={controlId}
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
        ref={triggerRef}
        type="button"
        className={`select-trigger ${selected ? 'has-value' : ''}`}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={menuId}
        aria-invalid={invalid}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={onTriggerKeyDown}
      >
        <span>{selected?.label ?? placeholder}</span>
        <svg className="select-chevron" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="m7 10 5 5 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <div className="select-menu" id={menuId} role="listbox" aria-hidden={!open}>
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
    </div>
  );
}
