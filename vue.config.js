const { defineConfig } = require('@vue/cli-service')
const webpack = require('webpack')

module.exports = defineConfig({
  publicPath: '/',
  devServer: {
    allowedHosts: 'all',
    port: 8080,
    host: '0.0.0.0',
    client: {
      overlay: {
        // Build/compile errors still get the full-screen overlay.
        errors: true,
        warnings: false,
        // The Beacon SDK rejects with plain `{title, description}`
        // objects (NOT Error instances), mostly during wallet connect —
        // user dismissed the popup, wallet doesn't support shadownet,
        // relay hiccup, etc. webpack-dev-server's overlay can't
        // stringify a non-Error and shows a useless "ERROR
        // [object Object]" box. App.vue already preventDefault()s these
        // on window, but that doesn't stop wds's *own* error listener —
        // this filter does. Genuine runtime errors still surface.
        runtimeErrors: (error) => {
          const parts = []
          if (error && typeof error === 'object') {
            parts.push(error.name, error.title, error.description, error.message)
            // Plain Beacon objects have no useful toString — JSON it so
            // the keyword probe can see title/description text.
            try { parts.push(JSON.stringify(error)) } catch (_e) { /* circular — skip */ }
            // A non-Error object carrying Beacon's signature shape.
            if (!(error instanceof Error) && error.title && error.description) {
              return false
            }
          } else {
            parts.push(String(error))
          }
          const probe = parts.filter(Boolean).join(' ').toLowerCase()
          if (
            /beaconerror|network_not_supported|not.*support.*network|aborted|user (closed|rejected)|cancell?ed|denied/.test(
              probe,
            )
          ) {
            return false
          }
          return true
        },
      },
    },
  },
  configureWebpack: {
    resolve: {
      fallback: {
        path: require.resolve('path-browserify'),
        stream: require.resolve('stream-browserify'),
        buffer: require.resolve('buffer'),
        process: require.resolve('process/browser'),
        crypto: false,
      },
    },
    plugins: [
      new webpack.ProvidePlugin({
        Buffer: ['buffer', 'Buffer'],
        process: 'process/browser',
      }),
    ],
  },
})
