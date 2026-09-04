import sealUrl from "../../../assets/auth/wealth-world-seal.png";

export function LoginBrand() {
  return (
    <div className="login-brand">
      <span className="login-brand__seal" aria-hidden="true">
        <img src={sealUrl} alt="" draggable={false} />
      </span>
      <h1 className="login-brand__title">财势天下</h1>
    </div>
  );
}
