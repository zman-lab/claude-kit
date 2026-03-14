export function printContent(title, htmlContent, mode = 'post') {
  const win = window.open('', '_blank')
  win.document.write(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>${title}</title>
      <style>
        body { font-family: -apple-system, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        pre { background: #f4f4f4; padding: 12px; border-radius: 4px; overflow-x: auto; }
        code { font-family: monospace; }
        img { max-width: 100%; }
        .reply { border-left: 3px solid #e5e7eb; padding-left: 12px; margin: 16px 0; }
        .reply-author { font-weight: bold; color: #374151; margin-bottom: 4px; }
        @media print { body { padding: 0; } }
      </style>
    </head>
    <body>${htmlContent}</body>
    </html>
  `)
  win.document.close()
  win.print()
}
