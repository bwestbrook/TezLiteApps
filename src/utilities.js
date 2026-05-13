// Shared math + helper utilities

export const radsToDegs = (rads) => (rads * 180) / Math.PI

export const degsToRads = (degs) => (degs * Math.PI) / 180

/**
 * Fetch and parse JSON from a URL.
 * Throws if the response is not OK or not valid JSON.
 */
export const getJsonObjectFromString = async (url) => {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status} ${response.statusText}`)
  }
  return response.json()
}

/**
 * Shorten a Tezos address to "t.<last 4>" for compact display.
 */
export const reduceAddress = (address) => `t.${address.substring(address.length - 4)}`

/**
 * Random integer in [min, max], inclusive on both ends.
 */
export const getRandomIntInclusive = (min, max) => {
  const lo = Math.ceil(min)
  const hi = Math.floor(max)
  return Math.floor(Math.random() * (hi - lo + 1)) + lo
}
