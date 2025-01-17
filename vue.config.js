const { defineConfig } = require('@vue/cli-service')
var webpack = require('webpack');
module.exports = defineConfig({
  publicPath: '/',
  devServer: {
    allowedHosts: 'all',
    port: 8080,
    host: '0.0.0.0'
    },
  configureWebpack: {
   
      resolve: {
        fallback: {
          path: require.resolve("path-browserify"),
          stream: require.resolve("stream-browserify"),
          buffer: require.resolve("buffer"),
          crypto: false,
        },
      },
      plugins: [
        new webpack.ProvidePlugin({
          Buffer:  ["buffer",  "Buffer"]
        })
      ]
    },
  }
)

