"use client";
import {useState} from "react";
import {parseRunTitle} from "@/lib/run-parser";
import type {translator} from "@/lib/i18n";

const labels:Record<string,string>={void_invasion:"Void Invasion",void_taint:"Void Taint",void_nightmare:"Void Nightmare",void_apocalypse:"Void Apocalypse",tower_of_disappearance:"Tower of Disappearance",duel_4:"Duel 4",loj_unlimited:"LoJ Unlimited"};
type T=ReturnType<typeof translator>;
const Cell=({label,value}:{label:string,value:string})=><div><small>{label}</small><b>{value}</b></div>;

export function ParserLab({t}:{t:T}){
  const[title,setTitle]=useState("그랜드체이스 클래식 아신 공허 침공 3층 01:07"),result=parseRunTitle(title),unknown=t("unidentified");
  return <section className="panel page lab"><p>{t("executableParser")}</p><h2>{t("pasteTitle")}</h2><textarea value={title} onChange={event=>setTitle(event.target.value)} aria-label={t("pasteTitle")}/><div className="parseGrid"><Cell label={t("character").toUpperCase()} value={result.character??unknown}/><Cell label={t("category")} value={result.category?labels[result.category]:unknown}/><Cell label={t("floor")} value={result.floor?`${result.floor}F`:unknown}/><Cell label={t("time")} value={result.timeLabel}/><Cell label={t("solo")} value={result.solo?t("yes"):t("notInformed")}/><Cell label={t("noPotions")} value={result.noPotions?t("yes"):t("notInformed")}/></div><div className="parseResult"><span className={result.status==="ready_for_review"?"good":"slow"}>{result.status}</span><b>{t("confidence",{value:result.confidence})}</b><small>{result.status==="time_required"?t("missingTime"):result.status==="classification_required"?t("reviewFields"):t("readyQueue")}</small></div></section>;
}
