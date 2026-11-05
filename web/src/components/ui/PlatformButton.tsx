import { Button } from 'antd';
import { forwardRef, type ButtonHTMLAttributes } from 'react';

/** Shared business button: HTML form semantics stay at the call site. */
export const PlatformButton = forwardRef<HTMLButtonElement, Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'color'>>(
  function PlatformButton({ type = 'button', className = '', children, ...props }, ref) {
    const classes = new Set(className.split(/\s+/));
    const primary = classes.has('primary') || classes.has('credentials-save');
    const link = classes.has('rd-link-button') || classes.has('feedback-link');
    return <Button {...props} ref={ref} htmlType={type} autoInsertSpace={false}
      type={primary ? 'primary' : link ? 'link' : 'default'} danger={classes.has('danger') || classes.has('danger-text')}
      size={classes.has('compact') ? 'small' : 'middle'} className={className}>{children}</Button>;
  },
);
