import React from "react";
import { credentialStorageHelp } from "../../../../shared/credential-storage-help.cjs";

export function SecureStorageNotice({ id, platform, editing, onOpenHelp }: {
  id: string;
  platform?: string;
  editing?: boolean;
  onOpenHelp: (event: React.MouseEvent<HTMLAnchorElement>, platform?: string) => void;
}): React.ReactElement {
  const help = credentialStorageHelp(platform);
  return <p className="cloud-field__help cloud-storage-notice" id={id} role="status">
    Secure storage isn’t available. <a className="cloud-field__help-link" href={help.url} target="_blank" rel="noopener noreferrer" onClick={(event) => onOpenHelp(event, help.platform)}>{help.label}</a>, then restart Studio.
    {" Or "}{editing ? "save" : "connect"} for this session; you’ll need to enter your token again after Studio restarts.
  </p>;
}
