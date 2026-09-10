export type TimeParts = {minutes:string; seconds:string; milliseconds:string};

export function splitTimeLabel(value:string):TimeParts {
  const match=value.match(/^(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?$/);
  return match
    ? {minutes:String(Number(match[1])),seconds:match[2],milliseconds:match[3]??""}
    : {minutes:"",seconds:"",milliseconds:""};
}

export function parseTimeParts(parts:TimeParts):number|null {
  if(!/^\d{1,2}$/.test(parts.minutes)||!/^\d{1,2}$/.test(parts.seconds)||
     (parts.milliseconds!==""&&!/^\d{1,3}$/.test(parts.milliseconds)))return null;
  const minutes=Number(parts.minutes),seconds=Number(parts.seconds);
  if(seconds>59)return null;
  const milliseconds=parts.milliseconds===""?0:Number(parts.milliseconds.padEnd(3,"0"));
  const result=(minutes*60+seconds)*1000+milliseconds;
  return result>0?result:null;
}

export function digitsOnly(value:string,maxLength:number):string {
  return value.replace(/\D/g,"").slice(0,maxLength);
}
