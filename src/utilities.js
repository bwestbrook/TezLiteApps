import $ from 'jquery'

export const radsToDegs = function(rads) {
    return rads * 180 / Math.PI;
}

export const degsToRads = function(degs) {
    return degs * Math.PI / 180;
}
  
export const getJsonObjectFromString = async(input_string) => {
const meta_data = await $.getJSON(input_string)
console.log(meta_data)
return meta_data
}

export const reduceAddress = async(address) => {
return 't.' + address.substring(address.length - 4)
}


export const getRandomIntInclusive = (min, max) => {
min = Math.ceil(min);
max = Math.floor(max);
return Math.floor(Math.random() * (max - min + 1)) + min; //The maximum is inclusive and the minimum is inclusive 
}

