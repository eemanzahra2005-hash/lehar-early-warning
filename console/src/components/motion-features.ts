// framer-motion's full DOM feature set (animations, gestures, layout), in its
// own module so <LazyMotion> can fetch it after first paint instead of
// shipping it in every route's initial bundle.
import { domMax } from "framer-motion";

export default domMax;
