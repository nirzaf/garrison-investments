import type { PointerEvent as ReactPointerEvent } from "react";
import { ArrowRight, X } from "lucide-react";

import { productTourSteps } from "@/lib/portal-data";

export type TourRect = {
  top: number;
  left: number;
  width: number;
  height: number;
};

export type TourModalPosition = {
  top: number;
  left: number;
};

export function getTourModalPosition(
  rect: TourRect,
  preferredPosition: "top" | "right" | "bottom" | "left" = "bottom",
): TourModalPosition {
  const gap = 14;
  const modalWidth = Math.min(390, window.innerWidth - 28);
  const modalHeight = Math.min(430, window.innerHeight - 28);
  const centeredLeft = rect.left + rect.width / 2 - modalWidth / 2;
  const clampLeft = (value: number) => Math.min(Math.max(value, 14), window.innerWidth - modalWidth - 14);
  const clampTop = (value: number) => Math.min(Math.max(value, 14), window.innerHeight - modalHeight - 14);

  if (preferredPosition === "top" && rect.top > modalHeight + gap) {
    return { top: clampTop(rect.top - modalHeight - gap), left: clampLeft(centeredLeft) };
  }

  if (preferredPosition === "right" && rect.left + rect.width + modalWidth + gap < window.innerWidth) {
    return { top: clampTop(rect.top), left: clampLeft(rect.left + rect.width + gap) };
  }

  if (preferredPosition === "left" && rect.left > modalWidth + gap) {
    return { top: clampTop(rect.top), left: clampLeft(rect.left - modalWidth - gap) };
  }

  if (rect.top + rect.height + modalHeight + gap < window.innerHeight) {
    return { top: clampTop(rect.top + rect.height + gap), left: clampLeft(centeredLeft) };
  }

  return { top: clampTop(rect.top - modalHeight - gap), left: clampLeft(centeredLeft) };
}

export function ProductTourOverlay({
  activeStep,
  index,
  targetRect,
  modalPosition,
  onClose,
  onNext,
  onPrev,
  onStep,
}: {
  activeStep: (typeof productTourSteps)[number];
  index: number;
  targetRect: TourRect | null;
  modalPosition: TourModalPosition | null;
  onClose: () => void;
  onNext: () => void;
  onPrev: () => void;
  onStep: (index: number) => void;
}) {
  const isFinalStep = index === productTourSteps.length - 1;
  const resolvedModalPosition =
    targetRect && typeof window !== "undefined"
      ? getTourModalPosition(targetRect, activeStep.position)
      : modalPosition;
  const runTourAction = (
    event: ReactPointerEvent<HTMLButtonElement>,
    action: () => void,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    action();
  };

  return (
    <div className="productTourLayer" aria-label="Interactive product tour" aria-modal="true" role="dialog">
      {targetRect ? (
        <>
          <div className="tourShade top" style={{ height: targetRect.top }} />
          <div
            className="tourShade left"
            style={{
              top: targetRect.top,
              width: targetRect.left,
              height: targetRect.height,
            }}
          />
          <div
            className="tourShade right"
            style={{
              top: targetRect.top,
              left: targetRect.left + targetRect.width,
              height: targetRect.height,
            }}
          />
          <div
            className="tourShade bottom"
            style={{ top: targetRect.top + targetRect.height }}
          />
          <div
            className="tourSpotlight"
            style={{
              top: targetRect.top,
              left: targetRect.left,
              width: targetRect.width,
              height: targetRect.height,
            }}
          />
        </>
      ) : (
        <div className="tourShade full" />
      )}

      <section
        className="tourInstructionModal"
        style={
          resolvedModalPosition
            ? { top: resolvedModalPosition.top, left: resolvedModalPosition.left }
            : undefined
        }
      >
        <button
          aria-label="Close walkthrough"
          className="tourCloseButton"
          data-tour-action="close"
          onPointerDown={(event) => runTourAction(event, onClose)}
          type="button"
        >
          <X size={16} />
        </button>
        <div className="tourModalBody">
          <span className="tourEyebrow">{activeStep.eyebrow}</span>
          <h2>{activeStep.title}</h2>
          <p>{activeStep.body}</p>
          <div className="tourInstruction">
            <strong>How to present it</strong>
            <span>{activeStep.instruction}</span>
          </div>
          <div className="tourProgress">
            <span>
              {index + 1} / {productTourSteps.length}
            </span>
            <div>
              {productTourSteps.map((step, stepIndex) => (
                <button
                  aria-label={`Go to ${step.title}`}
                  className={stepIndex === index ? "isActive" : ""}
                  data-tour-action="step"
                  data-tour-step={stepIndex}
                  key={step.title}
                  onPointerDown={(event) => runTourAction(event, () => onStep(stepIndex))}
                  type="button"
                />
              ))}
            </div>
          </div>
        </div>
        <div className="tourButtons">
          <button
            className="ghostButton"
            data-tour-action="prev"
            onPointerDown={(event) => runTourAction(event, onPrev)}
            type="button"
          >
            Previous
          </button>
          <button
            data-tour-action="next"
            onPointerDown={(event) => runTourAction(event, onNext)}
            type="button"
          >
            {isFinalStep ? "Restart tour" : "Next"}
            <ArrowRight size={17} />
          </button>
        </div>
      </section>
    </div>
  );
}

