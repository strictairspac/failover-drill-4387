import {api} from './client.js';
export const nodesAPI={list:()=>api('/nodes'),save:(data,id)=>api('/nodes'+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify(data)})};
export const scenariosAPI={list:()=>api('/scenarios'),create:data=>api('/scenarios',{method:'POST',body:JSON.stringify(data)})};
export const drillsAPI={list:()=>api('/drills'),get:id=>api('/drills/'+id),create:data=>api('/drills',{method:'POST',body:JSON.stringify(data)})};
export const quotesAPI={
  columns:()=>api('/quote/columns'),
  rows:()=>api('/quote/rows'),
  setPrice:(symbol,value)=>api('/quote/rows/'+symbol+'/price',{method:'PUT',body:JSON.stringify({value})}),
  swap:(request_id,label)=>api('/quote/swap',{method:'POST',body:JSON.stringify({request_id,label})}),
  page:(pageSize,token)=>api('/quote/pages',{method:'POST',body:JSON.stringify({page_size:pageSize}),headers:token?{'X-Quote-Cursor':token}:{}}),
  cursors:()=>api('/quote/cursors'),
  closeCursor:token=>api('/quote/cursors/'+token,{method:'DELETE'}),
  reclaim:()=>api('/quote/reclaim',{method:'POST',body:'{}'}),
  failover:scenarioId=>api('/quote/failover',{method:'POST',body:JSON.stringify({scenario_id:scenarioId??null})}),
};
